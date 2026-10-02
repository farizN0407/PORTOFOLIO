# Fariz Nararya Abhyasa — Portfolio

A responsive personal cybersecurity portfolio with a cinematic, premium visual direction inspired by the reference image. The public site and protected content manager use PostgreSQL for projects, certifications, activities, and admin credentials.

## Database and local setup

Requires Python 3.10+ and a PostgreSQL database. The app does not create a database server or provide database credentials; create a PostgreSQL database with your hosting provider or locally, then place its connection string in `.env` as `DATABASE_URL`.

1. Copy `.env.example` to `.env`.
2. Replace `DATABASE_URL` with your PostgreSQL connection string. Keep `sslmode=require` for hosted databases when supported.
3. Set `ADMIN_EMAIL`, a unique `ADMIN_PASSWORD` of at least 14 characters, and a long random `APP_SECRET`. Keep `.env` private; it is ignored by Git.
4. Install the PostgreSQL driver and start the app:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python app.py
   ```

5. Open `http://127.0.0.1:8000` for the portfolio and `http://127.0.0.1:8000/admin` for the dashboard.

On first startup the app creates its tables in the configured PostgreSQL database, stores the admin password as a PBKDF2 hash, and adds the known BINUS Cyber Security Community membership. The app connects using Psycopg 3 and PostgreSQL parameterized queries. No SQLite database is used.

When hosting behind HTTPS, set `COOKIE_SECURE=true`. Use a secret `APP_SECRET`, protect `DATABASE_URL`, and restrict database network access to the application where the provider allows it.

## Admin dashboard

The dashboard supports create, edit, delete, publish/hide, and display ordering for projects, certifications, and activities. Project images and certification documents can be uploaded from the entry editor. Accepted formats are PNG, JPG, WEBP, and PDF, with a 5 MB per-file limit. The binary file and its metadata are stored in PostgreSQL `BYTEA`; the public media route serves an attachment only while its linked entry is published. Removing or replacing an attachment also removes the old database row when it is no longer in use.

Only the email configured as `ADMIN_EMAIL` can sign in. There is no public sign-up or admin account management. Only an authenticated admin session can upload, preview unpublished files, or modify and delete content. Login uses signed, HTTP-only, SameSite cookies, PostgreSQL-backed sessions, CSRF tokens, login attempt throttling, input validation, and parameterized PostgreSQL statements. Public API routes are read-only. Keep database backups sized for uploaded files as well as table data.

## Public deployment

The included Dockerfile binds to `0.0.0.0`, enables production mode, and marks admin cookies `Secure`. Deploy the image on a Docker-capable host with HTTPS and configure these environment variables through the host's secret settings:

- `DATABASE_URL` — PostgreSQL connection string
- `ADMIN_EMAIL` — your sign-in email; only this account can authenticate
- `ADMIN_PASSWORD` — unique password, 14 or more characters
- `APP_SECRET` — long random signing secret
- `APP_ENV=production`, `COOKIE_SECURE=true`, `PORTFOLIO_HOST=0.0.0.0`
- `PORT` — usually supplied by the hosting platform

The public portfolio can be viewed without signing in. `/admin` presents a sign-in form, while admin API data and uploads remain behind authentication; the admin page is marked `noindex`. The app does not provision a hosting service or PostgreSQL instance. Keep the database URL and admin credentials in the host's secret settings, never in the repository.

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
