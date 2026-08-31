from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from supabase import create_client
from dotenv import load_dotenv
from groq import Groq
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_wtf.csrf import CSRFProtect
from PIL import Image
from io import BytesIO
import os
import re
import hmac

load_dotenv()

app = Flask(__name__)

# BUGFIX: without this, get_remote_address() (used by the rate limiter below)
# sees the IP of Render's/Cloudflare's proxy, not the real visitor — meaning
# EVERY visitor was being counted into one shared "200 per day / 50 per hour"
# bucket keyed to the proxy's IP. The homepage, hit by every visitor plus
# uptime-monitor pings, exhausted that shared budget first, which is why only
# "/" was returning 429s while lower-traffic pages weren't (yet). x_for=1
# trusts one hop of X-Forwarded-For, which matches Render's setup; raise it
# if you put another proxy in front later.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.getenv("SECRET_KEY")

# Reject any upload over 25MB before it's even fully read into memory —
# protects against someone POSTing a huge file to exhaust server resources.
# Raised from 10MB: that limit applies to the WHOLE multipart request, not
# per file, so selecting several screenshot-sized PNGs at once (e.g. dashboard
# / chart images, which run larger than typical photos) could exceed it even
# though each individual file was reasonable — and with no 413 handler (added
# below), that failure surfaced as a raw, unfriendly error page.
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

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

Services he can help with (short freelance / project work):
- End-to-end ML pipelines and model comparison
- Flask backends, REST APIs, Supabase
- Full-stack small apps (Flask + HTML/CSS + DB)
- Data scraping / API ingestion and cleaning
- Dashboards and LLM assistant features

Remember: SHORT answers only. 2-3 sentences maximum. No bullet points ever.
"""

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

# ── PUBLIC ROUTES ──────────────────────────────────────────

REACT_DIST = os.path.join(os.path.dirname(__file__) or ".", "react_dist")


@app.route("/assets/<path:filename>")
def react_assets(filename):
    """Serves the built React UI's JS/CSS/image bundle. Vite builds
    reference absolute "/assets/..." paths, so this mirrors that exactly —
    no vite.config changes needed."""
    return send_from_directory(os.path.join(REACT_DIST, "assets"), filename)


@app.route("/")
def index():
    # New React UI (zip2) is now the public homepage — it's a full one-page
    # site (hero/about/services/projects/capabilities/experience/contact all
    # in one scroll with anchor links), talking to /api/projects, /chat, and
    # /api/contact for live data instead of hardcoded content.
    #
    # Falls back to the original Jinja homepage if react_dist/index.html
    # hasn't been built yet (e.g. local dev before `npm run build`), so this
    # never hard-breaks the site.
    react_index = os.path.join(REACT_DIST, "index.html")
    if os.path.exists(react_index):
        return send_from_directory(REACT_DIST, "index.html")

    try:
        result = supabase.table("projects").select("*").order("created_at", desc=True).execute()
        projects = result.data or []
        projects.sort(key=lambda p: (p.get("featured_rank") is None, p.get("featured_rank") or 0))
    except Exception as e:
        print("Index load error:", e)
        projects = []
    return render_template("index.html", projects=projects)


def _shape_project_for_api(p, index):
    """Maps a raw Supabase `projects` row onto the shape the React UI's
    ProjectItem interface expects (src/types.ts in the new frontend repo).
    Kept in one place so the admin panel (source of truth) and the public
    site never drift out of sync — the UI never hardcodes project content."""
    architecture_text = p.get("architecture") or ""
    return {
        "id": p.get("slug"),
        "number": str(index + 1).zfill(2),
        "title": p.get("title"),
        # DB has one `category` field; the UI wants both a short subtitle and
        # a category label, so both reuse it rather than inventing content.
        "subtitle": p.get("category") or "",
        "category": p.get("category") or "",
        "description": p.get("description") or "",
        "longDescription": p.get("solution") or p.get("description") or "",
        "architectureDetails": [line.strip() for line in architecture_text.split("\n") if line.strip()],
        "metrics": [],  # no structured metrics column yet in Supabase
        "technologies": p.get("tags") or [],
        "image": p.get("image_url"),
        "screenshots": p.get("images") or [],
        "demoUrl": p.get("live_url"),
        "githubUrl": p.get("github_url"),
        "featured": p.get("featured_rank") is not None,
        "inProgress": p.get("status") == "coming_soon",
        "caseStudy": {
            "problem": p.get("problem"),
            "approach": p.get("solution"),
            "architecture": p.get("architecture"),
            "challenges": p.get("challenges"),
            "results": p.get("results"),
            "lessons": p.get("lessons_learned"),
            "nextSteps": p.get("future_improvements"),
        },
    }


@app.route("/api/projects")
def api_projects():
    """Public read-only JSON feed of projects, for the React frontend.
    Same data, same admin panel as the source of truth — nothing here is
    hardcoded, so editing a project in /admin updates the live site with
    no frontend redeploy needed."""
    try:
        result = supabase.table("projects").select("*").order("created_at", desc=True).execute()
        projects = result.data or []
        projects.sort(key=lambda p: (p.get("featured_rank") is None, p.get("featured_rank") or 0))
    except Exception as e:
        print("API projects load error:", e)
        projects = []
    shaped = [_shape_project_for_api(p, i) for i, p in enumerate(projects)]
    return jsonify(shaped)


@app.route("/projects/<slug>")
def project_detail(slug):
    try:
        result = supabase.table("projects").select("*").eq("slug", slug).execute()
    except Exception as e:
        print("Project detail load error:", e)
        return "Project not found", 404
    if not result.data:
        return "Project not found", 404
    project = result.data[0]
    # increment view count (best-effort — a failure here shouldn't stop the page loading)
    views = (project.get("views") or 0) + 1
    try:
        supabase.table("projects").update({"views": views}).eq("slug", slug).execute()
        project["views"] = views
    except Exception as e:
        print("View count update error:", e)
    return render_template("project.html", project=project)

# Friendly response when a rate limit is hit. Was previously returning the
# CHATBOT'S message ("You're sending messages...") for every 429, on every
# route — that's what showed up as raw JSON on the homepage. Now it only
# sends that message for the chat endpoint itself.
@app.errorhandler(429)
def ratelimit_handler(e):
    if request.path == "/chat":
        return jsonify({
            "reply": "You're sending messages a bit fast — please wait a moment and try again."
        }), 429
    return "Too many requests — please wait a moment and try again.", 429

# Friendly response when an upload exceeds MAX_CONTENT_LENGTH. Without this,
# Flask/Werkzeug returns a bare "413 Request Entity Too Large" page — this is
# what was showing up as "an error" when adding several images at once
# (e.g. dashboard/chart screenshots, which run bigger than typical photos)
# in the admin add/edit forms. JSON requests (like /chat) get a JSON reply;
# normal form posts (image uploads) get a flash message back on the referring
# page instead of a blank error page.
@app.errorhandler(413)
def too_large_handler(e):
    if request.path == "/chat":
        return jsonify({"reply": "That message was too large."}), 413
    flash(
        "That upload was too large (max 25MB total per save). Try adding "
        "fewer images at a time, or use smaller image files.",
        "error",
    )
    return redirect(request.referrer or url_for("admin"))

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
    try:
        result = supabase.table("projects").select("*").order("created_at", desc=True).execute()
        projects = result.data or []
    except Exception as e:
        print("Admin load error:", e)
        flash(f"Couldn't load projects: {e}", "error")
        projects = []
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
    # BUGFIX: this used to be pre-seeded with the site's own page URLs
    # (SITE_URL/, /about, /services, /contact) instead of starting empty --
    # copy-paste leftover from the sitemap() function below. That meant every
    # new project's "images" gallery contained those 4 non-image page links,
    # which the slideshow on project.html tried to render as <img> tags.
    image_urls = []

    images = request.files.getlist("images")
    failed_uploads = []
    for i, image in enumerate(images):
        if image and image.filename:
            try:
                file_bytes = image.read()
                if not is_allowed_image(file_bytes):
                    print(f"Rejected upload '{image.filename}': not a recognized image format")
                    failed_uploads.append(f"{image.filename} (not a recognized image format)")
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
                failed_uploads.append(f"{image.filename} ({e})")

    if failed_uploads:
        flash(
            "Some images couldn't be uploaded and were skipped: " + "; ".join(failed_uploads),
            "error",
        )

    try:
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
    except Exception as e:
        print("Add project error:", e)
        flash(f"Couldn't add the project: {e}", "error")

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

        # Load current project for existing images
        try:
            current = supabase.table("projects").select("*").eq("id", id).execute()
        except Exception as e:
            print("Edit project fetch error:", e)
            flash(f"Couldn't load the project to edit: {e}", "error")
            return redirect(url_for("admin"))
        if not current.data:
            flash("Project not found.", "error")
            return redirect(url_for("admin"))
        project = current.data[0]

        existing = list(project.get("images") or [])
        if not existing and project.get("image_url"):
            existing = [project["image_url"]]

        # Remove checked images
        remove_urls = set(request.form.getlist("remove_images"))
        kept = [u for u in existing if u not in remove_urls]

        # Try delete removed files from Supabase storage (best-effort)
        for url in remove_urls:
            try:
                # public URL ends with /project-images/<filename>
                if "/project-images/" in url:
                    file_name = url.split("/project-images/")[-1].split("?")[0]
                    supabase_admin.storage.from_("project-images").remove([file_name])
            except Exception as e:
                print("Storage delete error:", e)

        # Upload newly added images
        slug = project.get("slug") or slugify(title or "project")
        new_urls = []
        images = request.files.getlist("images")
        start_i = len(kept)
        failed_uploads = []
        for i, image in enumerate(images):
            if image and image.filename:
                try:
                    file_bytes = image.read()
                    if not is_allowed_image(file_bytes):
                        print(f"Rejected upload '{image.filename}': not a recognized image format")
                        failed_uploads.append(f"{image.filename} (not a recognized image format)")
                        continue
                    optimized, content_type, opt_ext = optimize_image(file_bytes)
                    file_ext = opt_ext or image.filename.rsplit(".", 1)[-1].lower()
                    content_type = content_type or image.content_type or "image/jpeg"
                    file_name = f"{slug}-{start_i + i}.{file_ext}"
                    supabase_admin.storage.from_("project-images").upload(
                        file_name,
                        optimized,
                        {"content-type": content_type, "upsert": "true"}
                    )
                    supabase_url = os.getenv("SUPABASE_URL")
                    url = f"{supabase_url}/storage/v1/object/public/project-images/{file_name}"
                    new_urls.append(url)
                except Exception as e:
                    print("Image upload error:", e)
                    failed_uploads.append(f"{image.filename} ({e})")

        if failed_uploads:
            flash(
                "Some images couldn't be uploaded and were skipped: " + "; ".join(failed_uploads),
                "error",
            )

        all_images = kept + new_urls
        image_url = all_images[0] if all_images else ""

        # Fields that have existed since the original schema.
        base_fields = {
            "title": title,
            "description": description,
            "live_url": live_url,
            "github_url": github_url,
            "tags": tags,
            "category": category,
            "images": all_images,
            "image_url": image_url,
        }
        # Case-study fields added later — these require
        # supabase-migration-case-study-fields.sql to have been run against
        # your Supabase table. If it hasn't, Postgres/PostgREST rejects the
        # whole update with an "unknown column" error, which used to bubble
        # up as an unhandled 500 ("external error") and silently discard
        # every edit, including the base fields above.
        case_study_fields = {
            "status": status,
            "problem": problem,
            "solution": solution,
            "architecture": architecture,
            "challenges": challenges,
            "results": results,
            "lessons_learned": lessons_learned,
            "future_improvements": future_improvements,
            "featured_rank": featured_rank,
        }

        try:
            supabase.table("projects").update({**base_fields, **case_study_fields}).eq("id", id).execute()
            flash("Project updated!")
        except Exception as e:
            print("Edit project update error (full):", e)
            # Fall back to saving just the base fields so the edit isn't
            # lost entirely, and tell the user exactly why the rest didn't save.
            try:
                supabase.table("projects").update(base_fields).eq("id", id).execute()
                flash(
                    "Saved title/description/links/images, but the case-study fields "
                    "(Status, Problem, Solution, Architecture, Challenges, Results, "
                    "Lessons, Next steps, Featured order) couldn't be saved. Run "
                    "supabase-migration-case-study-fields.sql against your Supabase "
                    "project, then try again.",
                    "error",
                )
            except Exception as e2:
                print("Edit project update error (base fields):", e2)
                flash(f"Couldn't save changes: {e2}", "error")

        return redirect(url_for("admin"))

    try:
        result = supabase.table("projects").select("*").eq("id", id).execute()
    except Exception as e:
        print("Edit project load error:", e)
        flash(f"Couldn't load the project: {e}", "error")
        return redirect(url_for("admin"))
    if not result.data:
        flash("Project not found.", "error")
        return redirect(url_for("admin"))
    project = result.data[0]
    return render_template("edit_project.html", project=project)


@app.route("/admin/delete/<id>", methods=["POST"])
def delete_project(id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    try:
        supabase.table("projects").delete().eq("id", id).execute()
        flash("Project deleted!")
    except Exception as e:
        print("Delete project error:", e)
        flash(f"Couldn't delete the project: {e}", "error")
    return redirect(url_for("admin"))

@app.route("/admin/upload-cv", methods=["POST"])
def upload_cv():
    if not session.get("admin"):
        return redirect(url_for("login"))
    cv = request.files.get("cv")
    if cv and cv.filename:
        file_bytes = cv.read()
        if not is_allowed_pdf(file_bytes):
            flash("That file doesn't look like a valid PDF.", "error")
            return redirect(url_for("admin"))
        try:
            # Write next to this file (app.py), not relative to the process's
            # current working directory — those aren't always the same,
            # especially under gunicorn, and a relative "static/" path would
            # silently write to (or fail against) the wrong folder.
            static_dir = os.path.join(os.path.dirname(__file__) or ".", "static")
            with open(os.path.join(static_dir, "cv.pdf"), "wb") as f:
                f.write(file_bytes)
            flash("CV uploaded successfully!")
        except Exception as e:
            print("CV upload error:", e)
            flash(f"Couldn't save the CV file: {e}", "error")
    return redirect(url_for("admin"))

@app.route("/services")
def services():
    return render_template("services.html")

def send_contact_email(name, email, subject, message):
    """Shared send logic for both the old Jinja contact form and the new
    React UI's JSON API — extracted so the two never drift out of sync.
    Returns (sent: bool, send_error: str|None, configured: bool)."""
    body = f"From: {name} <{email}>\nSubject: {subject}\n\n{message}"
    print(f"[CONTACT]\n{body}")

    try:
        log_dir = os.path.join(os.path.dirname(__file__) or ".", "instance")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "contact_messages.log"), "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"\n--- {datetime.utcnow().isoformat()}Z ---\n{body}\n")
    except Exception as e:
        print("Contact log write error:", e)

    sent = False
    send_error = None
    notify_to = (os.getenv("CONTACT_TO") or "razashakir919@gmail.com").strip()

    def env(key, default=""):
        v = os.getenv(key, default) or default
        return v.strip().strip('"').strip("'")

    resend_key = env("RESEND_API_KEY")
    if resend_key and not sent:
        try:
            import urllib.request
            import urllib.error
            import json as _json
            payload = _json.dumps({
                "from": env("RESEND_FROM") or "Portfolio <onboarding@resend.dev>",
                "to": [notify_to],
                "reply_to": email,
                "subject": f"[Portfolio] {subject}",
                "text": body,
            }).encode()
            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=payload,
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Portfolio-Contact-Form/1.0 (+https://shakirraza.onrender.com)",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    sent = True
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = "(could not read response body)"
            send_error = f"Resend: HTTP {e.code} — {detail}"
            print("Resend error:", send_error)
        except Exception as e:
            send_error = f"Resend: {e}"
            print("Resend error:", e)

    smtp_host = env("SMTP_HOST")
    smtp_user = env("SMTP_USER")
    smtp_pass = env("SMTP_PASS")
    smtp_port = env("SMTP_PORT") or "587"
    if smtp_host and smtp_user and smtp_pass and not sent:
        try:
            import smtplib
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["Subject"] = f"[Portfolio] {subject}"
            msg["From"] = smtp_user
            msg["To"] = notify_to
            msg["Reply-To"] = email
            msg.set_content(body)
            with smtplib.SMTP(smtp_host, int(smtp_port), timeout=20) as s:
                s.starttls()
                s.login(smtp_user, smtp_pass)
                s.send_message(msg)
            sent = True
        except Exception as e:
            send_error = f"SMTP: {e}"
            print("SMTP error:", e)

    configured = bool(smtp_host or resend_key)
    return sent, send_error, configured


@app.route("/contact", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def contact():
    """Public contact form — emails you when SMTP or RESEND is configured."""
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        subject = (request.form.get("subject") or "").strip() or "Portfolio contact"
        message = (request.form.get("message") or "").strip()

        if not name or not email or not message:
            flash("Please fill in name, email, and message.", "error")
            return render_template("contact.html"), 400
        if len(message) > 4000:
            flash("Message is too long.", "error")
            return render_template("contact.html"), 400

        sent, send_error, configured = send_contact_email(name, email, subject, message)

        if sent:
            flash("Thanks — your message was sent. I will reply by email.", "success")
        elif not configured:
            flash(
                "Message saved, but email is not configured on this server. "
                "Add SMTP_HOST, SMTP_USER, SMTP_PASS (and CONTACT_TO) in Render Environment, then redeploy.",
                "error",
            )
        else:
            flash(
                "Message saved, but sending email failed. Check server logs for SMTP/Resend errors "
                "(wrong app password, blocked login, etc.).",
                "error",
            )
            if send_error:
                print("Contact send_error detail:", send_error)
        return redirect(url_for("contact"))

    return render_template("contact.html")


@app.route("/api/contact", methods=["POST"])
@limiter.limit("5 per minute")
@csrf.exempt
def api_contact():
    """JSON version of /contact for the React UI's contact form. Same
    send_contact_email() helper as the Jinja form above — one code path,
    two entry points, so behavior can't drift between the two frontends."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    subject = (data.get("subject") or "").strip() or "Portfolio contact"
    message = (data.get("message") or "").strip()

    if not name or not email or not message:
        return jsonify({"ok": False, "error": "Please fill in name, email, and message."}), 400
    if len(message) > 4000:
        return jsonify({"ok": False, "error": "Message is too long."}), 400

    sent, send_error, configured = send_contact_email(name, email, subject, message)

    if sent:
        return jsonify({"ok": True, "message": "Thanks — your message was sent. I will reply by email."})
    if not configured:
        return jsonify({
            "ok": False,
            "error": "Message saved, but email isn't configured on the server yet.",
        }), 200
    return jsonify({
        "ok": False,
        "error": "Message saved, but sending the email failed. Please try again shortly.",
    }), 200


@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/robots.txt")
def robots():
    body = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    return app.response_class(body, mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap():
    try:
        result = supabase.table("projects").select("slug").execute()
        projects = result.data or []
    except Exception as e:
        print("Sitemap load error:", e)
        projects = []

    urls = [f"{SITE_URL}/", f"{SITE_URL}/about", f"{SITE_URL}/services"]
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