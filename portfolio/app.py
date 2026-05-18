from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from supabase import create_client
from dotenv import load_dotenv
from groq import Groq
import os
import re

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

supabase_admin = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

SYSTEM_PROMPT = """
You are Shakir Raza's personal AI assistant on his portfolio website.
Answer questions about Shakir naturally and helpfully.

About Shakir:
- Name: Shakir Raza
- Location: Karachi, Pakistan
- He is a CS student passionate about technology
- Specializes in Full Stack Development, AI/ML, and Data Science
- Currently building projects to sharpen his skills and showcase them

Skills:
- Python, Flask, HTML/CSS, Jinja2
- Tkinter for desktop apps
- AI/ML with Scikit-learn, Pandas, NumPy
- Data Science and data analysis
- SQL and Supabase
- Git and GitHub

Projects:
- Library Management System: Desktop app built with Python & Tkinter using BST and Queue data structures. Has role-based login for librarians and users.
- Snake Game: Classic snake game built with Python and Pygame
- Portfolio Website: This website! Built with Flask, Supabase, and deployed on Railway

Contact:
- Email: razashakir919@gmail.com
- GitHub: https://github.com/Shakir-Raza
- LinkedIn: https://www.linkedin.com/in/shakir-raza

Availability: Shakir is currently available for work and open to exciting opportunities.

Keep answers short, friendly and helpful. If asked something unrelated to Shakir, 
politely redirect the conversation back to Shakir's work and skills.
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

# ── CHATBOT ROUTE ──────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        history = data.get("history", [])

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

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
        return jsonify({"reply": response.text})
    except Exception as e:
        print("Chat error:", e)
        return jsonify({"reply": "Sorry, I'm having trouble right now. Please try again!"})
# ── ADMIN ROUTES ───────────────────────────────────────────

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))
    result = supabase.table("projects").select("*").order("created_at", desc=True).execute()
    projects = result.data
    return render_template("admin.html", projects=projects)

@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password")
        if password == ADMIN_PASSWORD:
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
                file_ext = image.filename.rsplit(".", 1)[-1].lower()
                file_name = f"{slug}-{i}.{file_ext}"
                supabase_admin.storage.from_("project-images").upload(
                    file_name,
                    file_bytes,
                    {"content-type": image.content_type, "upsert": "true"}
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
        cv.save(os.path.join("static", "cv.pdf"))
        flash("CV uploaded successfully!")
    return redirect(url_for("admin"))

@app.route("/about")
def about():
    return render_template("about.html")

if __name__ == "__main__":
    app.run(debug=True)