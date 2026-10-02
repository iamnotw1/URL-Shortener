# FastAPI URL Shortener

A lightweight, high-performance URL shortening and redirect service built with FastAPI, SQLite (SQLAlchemy), and Redis caching.

## Features
- **Deterministic Slugs:** Maps auto-incrementing database primary keys to Base62 alphanumeric slugs.
- **Cache-Aside Layer:** Leverages Redis with TTL expiration to serve high-throughput redirects without hitting SQLite.
- **Access Analytics:** Tracks visit counts, referrers, user agents, and timestamps per slug.
- **Interactive API Docs:** Built-in OpenAPI specification available via Swagger UI.

## Getting Started

1. **Clone repository & prepare environment:**
   ```bash
   git clone <REPO_URL>
   cd "URL Shortener"
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate


Install dependencies:

Bash
pip install -r requirements.txt
Start the application:

Bash
uvicorn main:app --reload --port 8000

Access the docs:
Navigate to http://127.0.0.1:8000/docs.
