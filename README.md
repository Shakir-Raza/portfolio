# Portfolio Website

Personal portfolio site with a self-built admin panel for managing project content, and an
AI chatbot that answers visitor questions about my background.

**Live site:** https://shakirraza.onrender.com/

---

## Problem Statement

Most student portfolios are static pages that need a code change and redeploy to update.
I wanted a portfolio I could actually manage — add projects, swap images, update tags — without
touching code each time.

## Solution

A Flask application backed by Supabase, with an admin panel for content management and a
Groq-hosted AI chatbot for interactive visitor questions.

## Architecture

![Architecture Diagram](architecture_portfolio.png)

## Tech Stack

Python, Flask, Jinja2, Supabase (PostgreSQL + Storage), Groq API, HTML, CSS, Render

## Features

- Admin panel for managing portfolio projects — add, delete, tag, and upload images —
  without redeploying
- Project images resized & compressed on upload, then stored via Supabase Storage
- AI chatbot (Groq-hosted Llama 3.1) with project-aware context, rate limiting, and
  error handling
- Case-study fields (problem, solution, architecture, results, lessons) per project
- Featured project ranking for homepage hierarchy
- Deployed to production on Render

## Screenshots

![Homepage](screenshots/homepage.png)
![Admin Panel](screenshots/admin-panel.png)
![Chatbot](screenshots/chatbot.png)

## Installation

```bash
git clone https://github.com/Shakir-Raza/portfolio.git
cd portfolio
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file with your own credentials (never commit this file):

```
SECRET_KEY=...
ADMIN_PASSWORD=...
SUPABASE_URL=...
SUPABASE_KEY=...
SUPABASE_SERVICE_KEY=...
GROQ_API_KEY=...
SITE_URL=https://shakirraza.onrender.com
```

## Usage

```bash
python app.py
```

Visit `http://localhost:5000`. Admin routes require login.

## Tests

```bash
python -m pytest test_app.py -q
```

Covers slugify, image/PDF magic-byte validation, and image optimization.

## Future Improvements

- Expand tests to cover admin CRUD routes with mocked Supabase
- Optional light/dark mode toggle
- Simple view-count analytics inside the admin panel
