from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from supabase import create_client
from dotenv import load_dotenv
from groq import Groq
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from PIL import Image
from io import BytesIO
import os
import re
import hmac

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Reject any upload over 10MB before it's even fully read into memory —
# protects against someone POSTing a huge file to exhaust server resources.
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# CSRF protection on every state-changing (POST/PUT/PATCH/DELETE) route.
# Forms need a hidden {{ csrf_token() }} field — already added to
# login.html, admin.html, and edit_project.html. /chat is exempted below
# since it's a read-only JSON API called via fetch(), not a session-changing form.
csrf = CSRFProtect(app)

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

supabase_admin = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
# Public site URL for sitemap/robots (no trailing slash). Falls back to Render domain.
SITE_URL = (os.getenv("SITE_URL") or "https://shakirraza.onrender.com").rstrip("/")

# Magic-byte check — verifies the file's actual content, not just the
# filename extension or the browser-supplied content-type (both spoofable).
def is_allowed_image(b):
    return (b.startswith(b"\xff\xd8\xff") or b.startswith(b"\x89PNG\r\n\x1a\n")
            or b.startswith((b"GIF87a", b"GIF89a"))
            or (b[:4] == b"RIFF" and b[8:12] == b"WEBP"))

def is_allowed_pdf(file_bytes):
    return file_bytes.startswith(b"%PDF-")

def optimize_image(file_bytes, max_width=1600, quality=82):
    """Resize and compress an image. Returns (optimized_bytes, content_type, ext).
    Falls back to original bytes if processing fails.
    """
    try:
        img = Image.open(BytesIO(file_bytes))
        img_format = (img.format or "JPEG").upper()

        # Convert palette / unusual modes so JPEG/WebP save works cleanly
        if img_format in ("JPEG", "JPG") and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode == "P":
            img = img.convert("RGBA")

        # Resize only if wider than max_width (preserve aspect ratio)
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        buf = BytesIO()
        if img_format in ("JPEG", "JPG"):
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            return buf.getvalue(), "image/jpeg", "jpg"
        elif img_format == "PNG":
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "image/png", "png"
        elif img_format == "WEBP":
            img.save(buf, format="WEBP", quality=quality, method=6)
            return buf.getvalue(), "image/webp", "webp"
        else:
            # GIF or unknown — keep original
            return file_bytes, None, None
    except Exception as e:
        print("Image optimize error:", e)
        return file_bytes, None, None

SYSTEM_PROMPT = """
You are Shakir Raza's personal AI assistant on his portfolio website.
Answer questions about Shakir naturally and helpfully.

About Shakir:
- AI/ML Engineer & Python Backend Developer, final-year CS student in Karachi, Pakistan
- NAVTTC-certified in AI & Machine Learning; completing Saylani's AI & Data Science program
- Builds end-to-end ML pipelines and Flask/Supabase backends, not just notebooks
- Highlight: a salary-prediction model at 0.112 RMSLE (Ridge regression, compared against XGBoost/LightGBM/GradientBoosting)

Skills: Python, Flask, Scikit-learn, XGBoost, LightGBM, Pandas, NumPy, SQL, Supabase, LLMs/Groq, Plotly, REST APIs, HTML/CSS, Git

Contact:
- Email: razashakir919@gmail.com
- GitHub: https://github.com/Shakir-Raza
- LinkedIn: https://www.linkedin.com/in/shakir-raza

Availability: currently available for work.

Remember: SHORT answers only. 2-3 sentences maximum. No bullet points ever.
"""

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

# ── PUBLIC ROUTES ──────────────────────────────────────────

@app.route("/")
def index():
    result = supabase.table("projects").select("*").order("created_at", desc=True).execute()
    projects = result.data
    # Sort by featured_rank when it's set (Phase 3 schema addition — see
    # supabase-migration-case-study-fields.sql). Projects without a rank
    # keep their original created_at-desc order, so this is a no-op until
    # you've run the migration and started setting ranks in the admin panel.
    projects.sort(key=lambda p: (p.get("featured_rank") is None, p.get("featured_rank") or 0))
    return render_template("index.html", projects=projects)

@app.route("/projects/<slug>")
def project_detail(slug):
    result = supabase.table("projects").select("*").eq("slug", slug).execute()
    if not result.data:
        return "Project not found", 404
    project = result.data[0]
    # increment view count
    views = (project.get("views") or 0) + 1
    supabase.table("projects").update({"views": views}).eq("slug", slug).execute()
    project["views"] = views
    return render_template("project.html", project=project)

# Friendly JSON response when chatbot rate limit is hit (controls API cost).
@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "reply": "You're sending messages a bit fast — please wait a moment and try again."
    }), 429

# ── CHATBOT ROUTE ──────────────────────────────────────────
@app.route("/chat", methods=["POST"])
@limiter.limit("20 per minute")
@csrf.exempt
def chat():
    try:
        data = request.get_json() or {}
        user_message = (data.get("message") or "").strip()
        history = data.get("history") or []

        # Cost / abuse guard: ignore empty or very long messages
        if not user_message:
            return jsonify({"reply": "Send a short question about Shakir's work or skills."})
        if len(user_message) > 500:
            return jsonify({"reply": "Please keep questions under 500 characters."})
        # Cap history sent to the model (already sliced client-side; enforce server-side too)
        history = history[-6:]

        # Pull richer project context so answers feel specific
        result = supabase.table("projects").select(
            "title, description, tags, status, live_url, github_url, problem, solution, results"
        ).execute()

        project_blocks = []
        for p in result.data or []:
            tags = ", ".join(p.get("tags") or []) or "none"
            status = p.get("status") or "live"
            block = f"- {p['title']} [{status}]\n  Summary: {p.get('description') or 'N/A'}\n  Tags: {tags}"
            if p.get("problem"):
                block += f"\n  Problem: {p['problem']}"
            if p.get("solution"):
                block += f"\n  Solution: {p['solution']}"
            if p.get("results"):
                block += f"\n  Results: {p['results']}"
            if p.get("live_url"):
                block += f"\n  Live: {p['live_url']}"
            if p.get("github_url"):
                block += f"\n  GitHub: {p['github_url']}"
            project_blocks.append(block)

        projects_text = "\n\n".join(project_blocks) or "No projects yet."

        dynamic_prompt = (
            SYSTEM_PROMPT
            + "\n\nCurrent Projects (use these details when answering):\n"
            + projects_text
            + "\n\nIf asked about a specific project, prefer the details above. "
              "If a field is missing, say you don't have that detail rather than inventing it."
        )

        messages = [{"role": "system", "content": dynamic_prompt}]
        for msg in history:
            messages.append({
                "role": msg["role"] if msg["role"] == "user" else "assistant",
                "content": msg["content"]
            })
        messages.append({"role": "user", "content": user_message})

        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        return jsonify({"reply": reply})

    except Exception as e:
        print("Chat error:", e)
        return jsonify({"reply": "Sorry, I'm having trouble right now. Please try again!"})
# ── ADMIN ROUTES ───────────────────────────────────────────

@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))
    result = supabase.table("projects").select("*").order("created_at", desc=True).execute()
    projects = result.data
    return render_template("admin.html", projects=projects)

@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        # hmac.compare_digest instead of == — prevents timing attacks, where
        # an attacker measures response time to guess the password
        # character-by-character. Both sides must be bytes of a fixed type.
        if ADMIN_PASSWORD and hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
            session["admin"] = True
            return redirect(url_for("admin"))
        else:
            flash("Wrong password!")
    return render_template("login.html")

@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin/add", methods=["POST"])
def add_project():
    if not session.get("admin"):
        return redirect(url_for("login"))

    title = request.form.get("title")
    description = request.form.get("description")
    live_url = request.form.get("live_url")
    github_url = request.form.get("github_url")
    tags = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]
    category = request.form.get("category", "other")
    slug = slugify(title)
    image_url = ""
    image_urls = []

    images = request.files.getlist("images")
    for i, image in enumerate(images):
        if image and image.filename:
            try:
                file_bytes = image.read()
                if not is_allowed_image(file_bytes):
                    print(f"Rejected upload '{image.filename}': not a recognized image format")
                    continue

                # Resize + compress before upload
                optimized, content_type, opt_ext = optimize_image(file_bytes)
                file_ext = opt_ext or image.filename.rsplit(".", 1)[-1].lower()
                content_type = content_type or image.content_type or "image/jpeg"
                file_name = f"{slug}-{i}.{file_ext}"

                supabase_admin.storage.from_("project-images").upload(
                    file_name,
                    optimized,
                    {"content-type": content_type, "upsert": "true"}
                )
                supabase_url = os.getenv("SUPABASE_URL")
                url = f"{supabase_url}/storage/v1/object/public/project-images/{file_name}"
                image_urls.append(url)
                if i == 0:
                    image_url = url
            except Exception as e:
                print("Image upload error:", e)

    supabase.table("projects").insert({
        "title": title,
        "description": description,
        "live_url": live_url,
        "github_url": github_url,
        "tags": tags,
        "slug": slug,
        "image_url": image_url,
        "images": image_urls,
        "category": category,
        "views": 0
    }).execute()

    flash("Project added successfully!")
    return redirect(url_for("admin"))

@app.route("/admin/edit/<id>", methods=["GET", "POST"])
def edit_project(id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        live_url = request.form.get("live_url")
        github_url = request.form.get("github_url")
        tags = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]
        category = request.form.get("category", "other")

        # Case-study fields — see supabase-migration-case-study-fields.sql.
        # These only take effect once that migration has been run; the
        # columns must exist in Supabase before this update() call will work.
        status = request.form.get("status", "live")
        problem = request.form.get("problem")
        solution = request.form.get("solution")
        architecture = request.form.get("architecture")
        challenges = request.form.get("challenges")
        results = request.form.get("results")
        lessons_learned = request.form.get("lessons_learned")
        future_improvements = request.form.get("future_improvements")
        featured_rank_raw = request.form.get("featured_rank", "").strip()
        featured_rank = int(featured_rank_raw) if featured_rank_raw.isdigit() else None

        supabase.table("projects").update({
            "title": title,
            "description": description,
            "live_url": live_url,
            "github_url": github_url,
            "tags": tags,
            "category": category,
            "status": status,
            "problem": problem,
            "solution": solution,
            "architecture": architecture,
            "challenges": challenges,
            "results": results,
            "lessons_learned": lessons_learned,
            "future_improvements": future_improvements,
            "featured_rank": featured_rank,
        }).eq("id", id).execute()

        flash("Project updated!")
        return redirect(url_for("admin"))

    result = supabase.table("projects").select("*").eq("id", id).execute()
    project = result.data[0]
    return render_template("edit_project.html", project=project)

@app.route("/admin/delete/<id>", methods=["POST"])
def delete_project(id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    supabase.table("projects").delete().eq("id", id).execute()
    flash("Project deleted!")
    return redirect(url_for("admin"))

@app.route("/admin/upload-cv", methods=["POST"])
def upload_cv():
    if not session.get("admin"):
        return redirect(url_for("login"))
    cv = request.files.get("cv")
    if cv and cv.filename:
        file_bytes = cv.read()
        if not is_allowed_pdf(file_bytes):
            flash("That file doesn't look like a valid PDF.")
            return redirect(url_for("admin"))
        with open(os.path.join("static", "cv.pdf"), "wb") as f:
            f.write(file_bytes)
        flash("CV uploaded successfully!")
    return redirect(url_for("admin"))

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/robots.txt")
def robots():
    body = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    return app.response_class(body, mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap():
    result = supabase.table("projects").select("slug").execute()
    projects = result.data

    urls = [f"{SITE_URL}/", f"{SITE_URL}/about"]
    urls += [f"{SITE_URL}/projects/{p['slug']}" for p in projects]

    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f"  <url><loc>{u}</loc></url>")
    xml.append("</urlset>")

    return app.response_class("\n".join(xml), mimetype="application/xml")

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

if __name__ == "__main__":
    app.run(debug=True)