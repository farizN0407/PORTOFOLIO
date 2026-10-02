# Fariz Nararya Abhyasa — Portfolio

A responsive personal cybersecurity portfolio with a cinematic, premium visual direction inspired by the reference image. The public site and protected content manager use PostgreSQL for projects, certifications, activities, and admin credentials.

## Database and local setup

Requires Python 3.10+ and a PostgreSQL database. The app does not create a database server or provide database credentials; create a PostgreSQL database with your hosting provider or locally, then place its connection string in `.env` as `DATABASE_URL`.

1. Copy `.env.example` to `.env`.
2. Replace `DATABASE_URL` with your PostgreSQL connection string. Keep `sslmode=require` for hosted databases when supported.
3. Set a long random `APP_SECRET`. Admin credentials are created once through the setup page; do not add them to `.env`.
4. Install the PostgreSQL driver and start the app:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python app.py
   ```

5. Open `http://127.0.0.1:8000` for the portfolio. Visit `http://127.0.0.1:8000/admin` to create the first admin account.

On first startup the app creates its tables in the configured PostgreSQL database and adds the known BINUS Cyber Security Community membership. If the `admins` table is empty, `/admin` offers a one-time account setup form. The first successful account creation permanently closes setup; afterward `/admin` only shows the sign-in form. Passwords are stored as PBKDF2 hashes. There is no public registration route. The app connects using Psycopg 3 and PostgreSQL parameterized queries. No SQLite database is used.

When hosting behind HTTPS, set `COOKIE_SECURE=true`. Use a secret `APP_SECRET`, protect `DATABASE_URL`, and restrict database network access to the application where the provider allows it.

## Admin dashboard

The dashboard supports create, edit, delete, publish/hide, and display ordering for projects, certifications, and activities. Project images and certification documents can be uploaded from the entry editor. Accepted formats are PNG, JPG, WEBP, and PDF, with a 5 MB per-file limit. The binary file and its metadata are stored in PostgreSQL `BYTEA`; the public media route serves an attachment only while its linked entry is published. Removing or replacing an attachment also removes the old database row when it is no longer in use.

There is only one admin account. The one-time setup form accepts an email and a unique password of at least 14 characters; protect the site with HTTPS and complete setup before sharing the public URL. Only an authenticated admin session can upload, preview unpublished files, or modify and delete content. Login uses signed, HTTP-only, SameSite cookies, PostgreSQL-backed sessions, CSRF tokens, login and setup attempt throttling, input validation, and parameterized PostgreSQL statements. Public API routes are read-only. Keep database backups sized for uploaded files as well as table data.

## Public deployment

The included Dockerfile binds to `0.0.0.0`, enables production mode, and marks admin cookies `Secure`. Deploy the image on a Docker-capable host with HTTPS and configure these environment variables through the host's secret settings:

- `DATABASE_URL` — PostgreSQL connection string
- `APP_SECRET` — long random signing secret
- `APP_ENV=production`, `COOKIE_SECURE=true`, `PORTFOLIO_HOST=0.0.0.0`
- `PORT` — usually supplied by the hosting platform

The public portfolio can be viewed without signing in. Before the first account is created, `/admin` presents the one-time setup form; once completed it presents only the sign-in form. Admin API data and uploads remain behind authentication; the admin page is marked `noindex`. The app does not provision a hosting service or PostgreSQL instance. Keep the database URL and app secret in the host's secret settings, never in the repository.

## Content notes

- Initial profile: Fariz Nararya Abhyasa, Bina Nusantara University, Cyber Security, Semester 5, 2024–Present, Blue Team focus.
- The published initial activity is BINUS Cyber Security Community — Member.
- Projects, certifications, contact details, and detailed skills remain blank until supplied.
- The hero background is an original generated asset at `assets/portfolio-hero.png`.

## Files

- `app.py` — web server, PostgreSQL schema initialization, public API, protected admin API and file handling
- `Dockerfile`, `.dockerignore` — container deployment
- `requirements.txt` — Psycopg 3 PostgreSQL driver
- `index.html`, `styles.css`, `extra.css`, `script.js` — public portfolio
- `admin.html`, `admin.css`, `admin-extra.css`, `admin.js` — content manager
- `.env.example` — configuration template; it contains no real credentials
