from flask import Flask, render_template, request, redirect, url_for, session, flash
from supabase import create_client
from dotenv import load_dotenv
import os
import re

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

# ─── PUBLIC ROUTES ───────────────────────────────────────

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
    return render_template("project.html", project=project)

# ─── ADMIN ROUTES ─────────────────────────────────────────

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
    slug = slugify(title)
    image_url = ""

    # Handle image upload
    image = request.files.get("image")
    if image and image.filename:
        file_bytes = image.read()
        file_ext = image.filename.rsplit(".", 1)[-1]
        file_name = f"{slug}.{file_ext}"
        supabase.storage.from_("project-images").upload(
            path=file_name,
            file=file_bytes,
            file_options={"content-type": image.content_type, "upsert": True}
)
        supabase_url = os.getenv("SUPABASE_URL")
        image_url = f"{supabase_url}/storage/v1/object/public/project-images/{file_name}"

    supabase.table("projects").insert({
        "title": title,
        "description": description,
        "live_url": live_url,
        "github_url": github_url,
        "tags": tags,
        "slug": slug,
        "image_url": image_url
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

if __name__ == "__main__":
    app.run(debug=True)