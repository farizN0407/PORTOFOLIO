"""Small web server and PostgreSQL API for the portfolio."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parent
ASSET_ROOT = ROOT / "assets"


def load_local_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
HOST = os.environ.get("PORTFOLIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
APP_ENV = os.environ.get("APP_ENV", "development").lower()
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SESSION_SECRET = os.environ.get("APP_SECRET", "")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
MAX_BODY = 128 * 1024
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SESSION_SECONDS = 60 * 60 * 8
PBKDF2_ROUNDS = 310_000
SETUP_COOKIE = "portfolio_setup"
SETUP_LOCK_ID = 739_105_221

TABLES = {
    "projects": {
        "title": "text", "summary": "text", "description": "text",
        "tools": "text", "category": "text", "github_url": "url",
        "external_url": "url", "featured": "bool", "thumbnail_id": "file",
    },
    "certifications": {
        "name": "text", "issuer": "text", "date": "text",
        "credential_url": "url", "credential_id": "text", "description": "text",
        "certificate_file_id": "file",
    },
    "activities": {
        "name": "text", "role": "text", "start_date": "text",
        "end_date": "text", "description": "text", "url": "url",
    },
}
RATE_LIMITS: dict[str, list[float]] = {}


def connect_db() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required. Configure a PostgreSQL connection string in .env.")
    return psycopg.connect(DATABASE_URL, connect_timeout=10, row_factory=dict_row)


def init_db() -> None:
    if APP_ENV == "production" and not COOKIE_SECURE:
        raise RuntimeError("Set COOKIE_SECURE=true when running in production over HTTPS.")
    if not SESSION_SECRET or SESSION_SECRET == "replace-with-a-long-random-secret":
        raise RuntimeError("Set APP_SECRET to a unique random value in .env before starting the server.")
    with connect_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS admins (
            id BIGSERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            salt BYTEA NOT NULL, password_hash BYTEA NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS admin_setup_state (
            id SMALLINT PRIMARY KEY CHECK (id = 1),
            completed BOOLEAN NOT NULL DEFAULT FALSE,
            completed_at TIMESTAMPTZ
        )""")
        db.execute("""INSERT INTO admin_setup_state (id, completed)
            SELECT 1, EXISTS(SELECT 1 FROM admins)
            ON CONFLICT (id) DO UPDATE SET completed = admin_setup_state.completed OR EXCLUDED.completed""")
        db.execute("""CREATE TABLE IF NOT EXISTS admin_sessions (
            token_hash BYTEA PRIMARY KEY,
            admin_id BIGINT NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
            csrf_token TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS profile_settings (
            id SMALLINT PRIMARY KEY CHECK (id = 1),
            email TEXT NOT NULL DEFAULT '',
            whatsapp TEXT NOT NULL DEFAULT '',
            linkedin_url TEXT NOT NULL DEFAULT '',
            github_url TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("INSERT INTO profile_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        db.execute("""CREATE TABLE IF NOT EXISTS uploaded_files (
            id BIGSERIAL PRIMARY KEY,
            original_name TEXT NOT NULL,
            media_type TEXT NOT NULL,
            data BYTEA NOT NULL,
            byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 5242880),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        for table, fields in TABLES.items():
            definitions = []
            for name, kind in fields.items():
                if kind == "file":
                    definitions.append(f'"{name}" BIGINT REFERENCES uploaded_files(id) ON DELETE SET NULL')
                    continue
                column_type = "BOOLEAN" if kind == "bool" else "TEXT"
                default = "FALSE" if kind == "bool" else "''"
                definitions.append(f'"{name}" {column_type} NOT NULL DEFAULT {default}')
            columns = ", ".join(definitions)
            db.execute(f"""CREATE TABLE IF NOT EXISTS "{table}" (
                id BIGSERIAL PRIMARY KEY, {columns},
                is_published BOOLEAN NOT NULL DEFAULT FALSE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            for name, kind in fields.items():
                if kind == "file":
                    db.execute(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{name}" BIGINT REFERENCES uploaded_files(id) ON DELETE SET NULL')
        db.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS slug TEXT")
        for project in db.execute("SELECT id, title FROM projects WHERE slug IS NULL OR slug = ''").fetchall():
            base = slugify(project["title"]) or f"project-{project['id']}"
            candidate = base
            suffix = 2
            while db.execute("SELECT 1 FROM projects WHERE slug = %s AND id <> %s", (candidate, project["id"])).fetchone():
                candidate = f"{base}-{suffix}"
                suffix += 1
            db.execute("UPDATE projects SET slug = %s WHERE id = %s", (candidate, project["id"]))
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS projects_slug_unique ON projects (slug)")
        db.execute("""CREATE TABLE IF NOT EXISTS project_attachments (
            id BIGSERIAL PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            file_id BIGINT NOT NULL REFERENCES uploaded_files(id) ON DELETE RESTRICT,
            title TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        owner = db.execute("SELECT id FROM admins ORDER BY id LIMIT 1").fetchone()
        if owner is not None:
            db.execute("DELETE FROM admins WHERE id <> %s", (owner["id"],))
        print("Admin setup available" if owner is None else "Single admin account ready")
        activity_count = db.execute("SELECT COUNT(*) AS count FROM activities").fetchone()["count"]
        if activity_count == 0:
            db.execute("INSERT INTO activities (name, role, is_published, sort_order) VALUES (%s, %s, TRUE, 0)", ("BINUS Cyber Security Community", "Member"))


def delete_file_if_unattached(db: psycopg.Connection, file_id: int | None) -> None:
    if file_id is None:
        return
    used = db.execute("""SELECT EXISTS(SELECT 1 FROM projects WHERE thumbnail_id = %s)
        OR EXISTS(SELECT 1 FROM certifications WHERE certificate_file_id = %s)
        OR EXISTS(SELECT 1 FROM project_attachments WHERE file_id = %s) AS used""", (file_id, file_id, file_id)).fetchone()["used"]
    if not used:
        db.execute("DELETE FROM uploaded_files WHERE id = %s", (file_id,))


def json_bytes(value: object) -> bytes:
    def encode_extra(item: object) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"Cannot serialize {type(item).__name__}")

    return json.dumps(value, ensure_ascii=False, default=encode_extra).encode("utf-8")


def validate_url(value: str) -> bool:
    return not value or (len(value) <= 2048 and value.startswith(("https://", "http://")))


def validate_profile_url(value: str) -> bool:
    if not value:
        return True
    parsed = urlparse(value)
    return len(value) <= 2048 and parsed.scheme in ("http", "https") and bool(parsed.hostname) and not re.search(r"\s", value)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalized)).strip("-")[:160].strip("-")


def allow_auth_attempt(ip: str) -> bool:
    now = time.time()
    attempts = [stamp for stamp in RATE_LIMITS.get(ip, []) if now - stamp < 300]
    if len(attempts) >= 8:
        RATE_LIMITS[ip] = attempts
        return False
    RATE_LIMITS[ip] = attempts + [now]
    return True


def admin_setup_available() -> bool:
    with connect_db() as db:
        row = db.execute("""SELECT completed OR EXISTS(SELECT 1 FROM admins) AS is_closed
            FROM admin_setup_state WHERE id = 1""").fetchone()
        return not row["is_closed"]


class PortfolioHandler(BaseHTTPRequestHandler):
    server_version = "PortfolioServer/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, status: int, value: object, cookie: str | None = None) -> None:
        body = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_uploaded_file(self, file_record: dict[str, object], *, inline: bool = False) -> None:
        media_type = str(file_record["media_type"])
        filename = str(file_record["original_name"]).replace("\\", "/").rsplit("/", 1)[-1]
        filename = re.sub(r"[\x00-\x1f\x7f]", "", filename).strip()[:180] or "download"
        safe_filename = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip(" .") or "download"
        disposition = "inline" if inline or media_type.startswith("image/") else "attachment"
        body = bytes(file_record["data"])
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'{disposition}; filename="{safe_filename}"; filename*=UTF-8\'\'{quote(filename, safe="")}' )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        # Visibility depends on the parent record's current publish state, so intermediaries must not retain the bytes.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def uploaded_file_body(self) -> tuple[str, str, bytes]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid file size") from error
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            raise ValueError("Files must be between 1 byte and 5 MB")
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        filename_header = self.headers.get("X-File-Name", "")
        try:
            filename = unquote(filename_header, errors="strict")
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("Invalid filename") from error
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        filename = re.sub(r"[\x00-\x1f\x7f]", "", filename).strip()[:180]
        extension = Path(filename).suffix.lower()
        allowed = {
            ".png": ("image/png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
            ".jpg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
            ".jpeg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
            ".webp": ("image/webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
            ".pdf": ("application/pdf", lambda data: data.startswith(b"%PDF-")),
        }
        if not filename or extension not in allowed:
            raise ValueError("Upload a PNG, JPG, WEBP, or PDF file")
        expected_type, signature_check = allowed[extension]
        if media_type != expected_type:
            raise ValueError("File type does not match its extension")
        data = self.rfile.read(length)
        if len(data) != length or not signature_check(data):
            raise ValueError("The file content is invalid or incomplete")
        return filename, media_type, data

    def body_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("Request body is empty or too large")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data

    def session(self) -> dict[str, object] | None:
        cookies = self.headers.get("Cookie", "")
        token = next((piece.strip()[10:] for piece in cookies.split(";") if piece.strip().startswith("portfolio=")), "")
        if "." not in token:
            return None
        sid, signature = token.split(".", 1)
        expected = hmac.new(SESSION_SECRET.encode(), sid.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        token_hash = hashlib.sha256(sid.encode()).digest()
        with connect_db() as db:
            row = db.execute("""SELECT a.email, s.csrf_token FROM admin_sessions s
                JOIN admins a ON a.id = s.admin_id
                WHERE s.token_hash = %s AND s.expires_at > CURRENT_TIMESTAMP""", (token_hash,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE admin_sessions SET expires_at = %s WHERE token_hash = %s", (datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS), token_hash))
        return {"email": row["email"], "csrf": row["csrf_token"]}

    def require_session(self) -> dict[str, object] | None:
        current = self.session()
        if current is None:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Please sign in"})
            return None
        if self.command in ("POST", "PUT", "PATCH", "DELETE"):
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin and urlparse(origin).netloc != host:
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid request origin"})
                return None
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), str(current["csrf"])):
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid security token"})
                return None
        return current

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/public/profile":
            with connect_db() as db:
                profile = db.execute("SELECT email, whatsapp, linkedin_url, github_url, phone FROM profile_settings WHERE id = 1").fetchone()
            self.send_json(HTTPStatus.OK, dict(profile) if profile else {"email": "", "whatsapp": "", "linkedin_url": "", "github_url": "", "phone": ""})
            return
        if parsed.path == "/api/admin/status":
            setup_required = admin_setup_available()
            if setup_required:
                setup_token = secrets.token_urlsafe(32)
                secure = "; Secure" if COOKIE_SECURE else ""
                self.send_json(HTTPStatus.OK, {"setup_required": True, "setup_csrf": setup_token}, f"{SETUP_COOKIE}={setup_token}; Path=/; Max-Age=600; HttpOnly; SameSite=Strict{secure}")
            else:
                secure = "; Secure" if COOKIE_SECURE else ""
                self.send_json(HTTPStatus.OK, {"setup_required": False}, f"{SETUP_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{secure}")
            return
        match = re.fullmatch(r"/api/public/(projects|certifications|activities)", parsed.path)
        if match:
            table = match.group(1)
            with connect_db() as db:
                if table == "projects":
                    rows = db.execute("""SELECT p.*, CASE WHEN f.id IS NULL THEN NULL ELSE '/media/' || f.id::text END AS thumbnail_url
                        FROM projects p LEFT JOIN uploaded_files f ON f.id = p.thumbnail_id
                        WHERE p.is_published IS TRUE ORDER BY p.sort_order, p.id DESC""").fetchall()
                elif table == "certifications":
                    rows = db.execute("""SELECT c.*, CASE WHEN f.id IS NULL THEN NULL ELSE '/media/' || f.id::text END AS certificate_file_url
                        FROM certifications c LEFT JOIN uploaded_files f ON f.id = c.certificate_file_id
                        WHERE c.is_published IS TRUE ORDER BY c.sort_order, c.id DESC""").fetchall()
                else:
                    rows = db.execute(f'SELECT * FROM "{table}" WHERE is_published IS TRUE ORDER BY sort_order, id DESC').fetchall()
            self.send_json(HTTPStatus.OK, [dict(row) for row in rows])
            return
        detail_match = re.fullmatch(r"/api/public/projects/([a-z0-9]+(?:-[a-z0-9]+)*)", parsed.path)
        if detail_match:
            with connect_db() as db:
                project = db.execute("""SELECT p.*, CASE WHEN f.id IS NULL THEN NULL ELSE '/media/' || f.id::text END AS thumbnail_url
                    FROM projects p LEFT JOIN uploaded_files f ON f.id = p.thumbnail_id
                    WHERE p.slug = %s AND p.is_published IS TRUE""", (detail_match.group(1),)).fetchone()
                if project:
                    attachments = db.execute("""SELECT a.id, a.title, a.display_order, a.created_at,
                            f.original_name AS filename, f.media_type, f.byte_size, '/project-attachments/' || a.id::text AS url
                        FROM project_attachments a JOIN uploaded_files f ON f.id = a.file_id
                        WHERE a.project_id = %s AND EXISTS (SELECT 1 FROM projects p WHERE p.id = a.project_id AND p.is_published IS TRUE)
                        ORDER BY a.display_order, a.id""", (project["id"],)).fetchall()
                else:
                    attachments = []
            if not project:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Project not found"})
            else:
                result = dict(project)
                result["write_ups"] = [dict(row) for row in attachments]
                self.send_json(HTTPStatus.OK, result)
            return
        attachment_public_match = re.fullmatch(r"/project-attachments/(\d+)", parsed.path)
        if attachment_public_match:
            with connect_db() as db:
                file_record = db.execute("""SELECT f.* FROM project_attachments a
                    JOIN uploaded_files f ON f.id = a.file_id JOIN projects p ON p.id = a.project_id
                    WHERE a.id = %s AND p.is_published IS TRUE""", (int(attachment_public_match.group(1)),)).fetchone()
            if file_record is None:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self.send_uploaded_file(file_record, inline=True)
            return
        media_match = re.fullmatch(r"/media/(\d+)", parsed.path)
        if media_match:
            media_id = int(media_match.group(1))
            with connect_db() as db:
                file_record = db.execute("""SELECT f.* FROM uploaded_files f
                    WHERE f.id = %s AND (
                        EXISTS (SELECT 1 FROM projects p WHERE p.thumbnail_id = f.id AND p.is_published IS TRUE)
                        OR EXISTS (SELECT 1 FROM certifications c WHERE c.certificate_file_id = f.id AND c.is_published IS TRUE)
                    )""", (media_id,)).fetchone()
            if file_record is None:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self.send_uploaded_file(file_record)
            return
        if parsed.path == "/api/admin/session":
            current = self.require_session()
            if current:
                self.send_json(HTTPStatus.OK, {"email": current["email"], "csrf": current["csrf"]})
            return
        if parsed.path.startswith("/api/admin/"):
            current = self.require_session()
            if current is None:
                return
            file_match = re.fullmatch(r"/api/admin/files/(\d+)", parsed.path)
            if file_match:
                with connect_db() as db:
                    file_record = db.execute("SELECT * FROM uploaded_files WHERE id = %s", (int(file_match.group(1)),)).fetchone()
                if file_record is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self.send_uploaded_file(file_record, inline=True)
                return
            if parsed.path == "/api/admin/profile":
                with connect_db() as db:
                    profile = db.execute("SELECT email, whatsapp, linkedin_url, github_url, phone FROM profile_settings WHERE id = 1").fetchone()
                self.send_json(HTTPStatus.OK, dict(profile) if profile else {})
                return
            attachment_match = re.fullmatch(r"/api/admin/projects/(\d+)/attachments", parsed.path)
            if attachment_match:
                with connect_db() as db:
                    rows = db.execute("""SELECT a.id, a.project_id, a.file_id, a.title, a.display_order, a.created_at,
                            f.original_name, f.media_type, f.byte_size
                        FROM project_attachments a JOIN uploaded_files f ON f.id = a.file_id
                        WHERE a.project_id = %s ORDER BY a.display_order, a.id""", (int(attachment_match.group(1)),)).fetchall()
                self.send_json(HTTPStatus.OK, [dict(row) for row in rows])
                return
            match = re.fullmatch(r"/api/admin/(projects|certifications|activities)", parsed.path)
            if match:
                with connect_db() as db:
                    table = match.group(1)
                    if table == "projects":
                        rows = db.execute("""SELECT p.*, f.original_name AS attachment_name FROM projects p
                            LEFT JOIN uploaded_files f ON f.id = p.thumbnail_id ORDER BY p.sort_order, p.id DESC""").fetchall()
                    elif table == "certifications":
                        rows = db.execute("""SELECT c.*, f.original_name AS attachment_name FROM certifications c
                            LEFT JOIN uploaded_files f ON f.id = c.certificate_file_id ORDER BY c.sort_order, c.id DESC""").fetchall()
                    else:
                        rows = db.execute(f'SELECT * FROM "{table}" ORDER BY sort_order, id DESC').fetchall()
                self.send_json(HTTPStatus.OK, [dict(row) for row in rows])
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/admin/setup":
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if not origin or urlparse(origin).netloc != host:
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid request origin"})
                return
            ip = self.client_address[0]
            if not allow_auth_attempt(ip):
                self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Too many attempts. Try again in a few minutes."})
                return
            cookies = self.headers.get("Cookie", "")
            setup_cookie = next((piece.strip()[len(SETUP_COOKIE) + 1:] for piece in cookies.split(";") if piece.strip().startswith(f"{SETUP_COOKIE}=")), "")
            setup_header = self.headers.get("X-CSRF-Token", "")
            if not setup_cookie or not hmac.compare_digest(setup_cookie, setup_header):
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid security token"})
                return
            secure = "; Secure" if COOKIE_SECURE else ""
            if not admin_setup_available():
                self.send_json(HTTPStatus.CONFLICT, {"error": "Admin setup has already been completed", "setup_required": False}, f"{SETUP_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{secure}")
                return
            try:
                payload = self.body_json()
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request"})
                return
            email = str(payload.get("email", "")).strip().lower()
            password = str(payload.get("password", ""))
            confirmation = str(payload.get("password_confirmation", ""))
            if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Enter a valid email address"})
                return
            if len(password) < 14 or len(password) > 1024:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Use a password with at least 14 characters"})
                return
            if password != confirmation:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Passwords do not match"})
                return
            salt = secrets.token_bytes(16)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
            with connect_db() as db:
                db.execute("SELECT pg_advisory_xact_lock(%s)", (SETUP_LOCK_ID,))
                setup_state = db.execute("SELECT completed FROM admin_setup_state WHERE id = 1 FOR UPDATE").fetchone()
                admin_present = db.execute("SELECT EXISTS(SELECT 1 FROM admins) AS present").fetchone()["present"]
                if setup_state["completed"] or admin_present:
                    self.send_json(HTTPStatus.CONFLICT, {"error": "Admin setup has already been completed", "setup_required": False}, f"{SETUP_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{secure}")
                    return
                db.execute("INSERT INTO admins (email, salt, password_hash) VALUES (%s, %s, %s)", (email, salt, digest))
                db.execute("UPDATE admin_setup_state SET completed = TRUE, completed_at = CURRENT_TIMESTAMP WHERE id = 1")
            RATE_LIMITS.pop(ip, None)
            secure = "; Secure" if COOKIE_SECURE else ""
            self.send_json(HTTPStatus.CREATED, {"created": True}, f"{SETUP_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{secure}")
            return
        if parsed.path == "/api/admin/login":
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin and urlparse(origin).netloc != host:
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid request origin"})
                return
            ip = self.client_address[0]
            if not allow_auth_attempt(ip):
                self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Too many attempts. Try again in a few minutes."})
                return
            try:
                payload = self.body_json()
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request"})
                return
            email = str(payload.get("email", "")).strip().lower()
            password = str(payload.get("password", ""))
            with connect_db() as db:
                admin = db.execute("SELECT * FROM admins WHERE email = %s", (email,)).fetchone()
            valid = False
            if admin:
                digest = hashlib.pbkdf2_hmac("sha256", password.encode(), admin["salt"], PBKDF2_ROUNDS)
                valid = hmac.compare_digest(digest, admin["password_hash"])
            else:
                hashlib.pbkdf2_hmac("sha256", password.encode(), b"portfolio-dummy-salt", PBKDF2_ROUNDS)
            if not valid:
                self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Email or password is incorrect"})
                return
            RATE_LIMITS.pop(ip, None)
            sid = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)
            token_hash = hashlib.sha256(sid.encode()).digest()
            with connect_db() as db:
                db.execute("INSERT INTO admin_sessions (token_hash, admin_id, csrf_token, expires_at) VALUES (%s, %s, %s, %s)", (token_hash, admin["id"], csrf, expires_at))
            signature = hmac.new(SESSION_SECRET.encode(), sid.encode(), hashlib.sha256).hexdigest()
            secure = "; Secure" if COOKIE_SECURE else ""
            self.send_json(HTTPStatus.OK, {"email": email, "csrf": csrf}, f"portfolio={sid}.{signature}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; SameSite=Strict{secure}")
            return
        if parsed.path == "/api/admin/logout":
            current = self.require_session()
            if current is None:
                return
            cookies = self.headers.get("Cookie", "")
            token = next((piece.strip()[10:] for piece in cookies.split(";") if piece.strip().startswith("portfolio=")), "")
            sid = token.split(".", 1)[0]
            token_hash = hashlib.sha256(sid.encode()).digest()
            with connect_db() as db:
                db.execute("DELETE FROM admin_sessions WHERE token_hash = %s", (token_hash,))
            secure = "; Secure" if COOKIE_SECURE else ""
            self.send_json(HTTPStatus.OK, {"ok": True}, f"portfolio=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{secure}")
            return
        if parsed.path == "/api/admin/files":
            if self.require_session() is None:
                return
            try:
                filename, media_type, data = self.uploaded_file_body()
            except ValueError as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            with connect_db() as db:
                row = db.execute("""INSERT INTO uploaded_files (original_name, media_type, data, byte_size)
                    VALUES (%s, %s, %s, %s) RETURNING id""", (filename, media_type, data, len(data))).fetchone()
            self.send_json(HTTPStatus.CREATED, {"id": row["id"], "filename": filename, "media_type": media_type, "byte_size": len(data)})
            return
        attachment_match = re.fullmatch(r"/api/admin/projects/(\d+)/attachments", parsed.path)
        if attachment_match:
            if self.require_session() is None:
                return
            try:
                filename, media_type, data = self.uploaded_file_body()
                title = unquote(self.headers.get("X-Attachment-Title", "")).strip() or Path(filename).stem
                display_order = int(self.headers.get("X-Display-Order", "0"))
                if len(title) > 240:
                    raise ValueError("Attachment title must be 240 characters or fewer")
                if abs(display_order) > 1_000_000:
                    raise ValueError("Display order is out of range")
            except (ValueError, UnicodeDecodeError) as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error) or "Invalid attachment"})
                return
            project_id = int(attachment_match.group(1))
            with connect_db() as db:
                if not db.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,)).fetchone():
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Project not found"})
                    return
                file_row = db.execute("""INSERT INTO uploaded_files (original_name, media_type, data, byte_size)
                    VALUES (%s, %s, %s, %s) RETURNING id""", (filename, media_type, data, len(data))).fetchone()
                row = db.execute("""INSERT INTO project_attachments (project_id, file_id, title, display_order)
                    VALUES (%s, %s, %s, %s) RETURNING id, project_id, file_id, title, display_order, created_at""",
                    (project_id, file_row["id"], title, display_order)).fetchone()
            self.send_json(HTTPStatus.CREATED, {**dict(row), "original_name": filename, "media_type": media_type, "byte_size": len(data)})
            return
        if parsed.path.startswith("/api/admin/"):
            current = self.require_session()
            if current is None:
                return
            match = re.fullmatch(r"/api/admin/(projects|certifications|activities)", parsed.path)
            if not match:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            self.mutate_content(match.group(1), None)
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_PUT(self) -> None:
        if not self.require_session():
            return
        if urlparse(self.path).path == "/api/admin/profile":
            try:
                incoming = self.body_json()
                if not isinstance(incoming, dict):
                    raise ValueError("Invalid profile details")
                email = str(incoming.get("email", "")).strip().lower()
                whatsapp_raw = str(incoming.get("whatsapp", "")).strip()
                linkedin_url = str(incoming.get("linkedin_url", "")).strip()
                github_url = str(incoming.get("github_url", "")).strip()
                phone = str(incoming.get("phone", "")).strip()
                if email and (len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
                    raise ValueError("Enter a valid email address")
                if len(whatsapp_raw) > 40 or re.search(r"[^0-9+() .-]", whatsapp_raw):
                    raise ValueError("Enter a valid WhatsApp number using digits and optional +, spaces, parentheses, or hyphens")
                whatsapp = re.sub(r"\D", "", whatsapp_raw)
                if whatsapp and (not re.fullmatch(r"[1-9][0-9]{7,14}", whatsapp)):
                    raise ValueError("WhatsApp number must include the country code and contain 8 to 15 digits")
                if not validate_profile_url(linkedin_url):
                    raise ValueError("LinkedIn URL must start with http:// or https://")
                if not validate_profile_url(github_url):
                    raise ValueError("GitHub URL must start with http:// or https://")
                phone_digits = re.sub(r"\D", "", phone)
                if len(phone) > 40 or (phone and (not re.fullmatch(r"\+?[0-9(). -]+", phone) or not 5 <= len(phone_digits) <= 15)):
                    raise ValueError("Enter a valid phone number")
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error) or "Invalid profile details"})
                return
            with connect_db() as db:
                row = db.execute("""UPDATE profile_settings SET email = %s, whatsapp = %s, linkedin_url = %s,
                    github_url = %s, phone = %s, updated_at = CURRENT_TIMESTAMP WHERE id = 1
                    RETURNING email, whatsapp, linkedin_url, github_url, phone""",
                    (email, whatsapp, linkedin_url, github_url, phone)).fetchone()
            self.send_json(HTTPStatus.OK, dict(row))
            return
        attachment_match = re.fullmatch(r"/api/admin/projects/(\d+)/attachments/(\d+)", urlparse(self.path).path)
        if attachment_match:
            try:
                incoming = self.body_json()
                title = str(incoming.get("title", "")).strip()
                display_order = int(incoming.get("display_order", 0))
                if not title or len(title) > 240:
                    raise ValueError("Attachment title is required and must be 240 characters or fewer")
                if abs(display_order) > 1_000_000:
                    raise ValueError("Display order is out of range")
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error) or "Invalid request"})
                return
            with connect_db() as db:
                cursor = db.execute("""UPDATE project_attachments SET title = %s, display_order = %s
                    WHERE project_id = %s AND id = %s""", (title, display_order, int(attachment_match.group(1)), int(attachment_match.group(2))))
                row = db.execute("""SELECT a.id, a.project_id, a.file_id, a.title, a.display_order, a.created_at,
                    f.original_name, f.media_type, f.byte_size FROM project_attachments a
                    JOIN uploaded_files f ON f.id = a.file_id WHERE a.project_id = %s AND a.id = %s""",
                    (int(attachment_match.group(1)), int(attachment_match.group(2)))).fetchone() if cursor.rowcount else None
            if row is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Attachment not found"})
            else:
                self.send_json(HTTPStatus.OK, dict(row))
            return
        match = re.fullmatch(r"/api/admin/(projects|certifications|activities)/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        self.mutate_content(match.group(1), int(match.group(2)))

    def do_DELETE(self) -> None:
        if not self.require_session():
            return
        file_match = re.fullmatch(r"/api/admin/files/(\d+)", urlparse(self.path).path)
        if file_match:
            file_id = int(file_match.group(1))
            with connect_db() as db:
                used = db.execute("""SELECT EXISTS(SELECT 1 FROM projects WHERE thumbnail_id = %s)
                    OR EXISTS(SELECT 1 FROM certifications WHERE certificate_file_id = %s)
                    OR EXISTS(SELECT 1 FROM project_attachments WHERE file_id = %s) AS used""", (file_id, file_id, file_id)).fetchone()["used"]
                if used:
                    self.send_json(HTTPStatus.CONFLICT, {"error": "Remove this file from its entry before deleting it"})
                    return
                cursor = db.execute("DELETE FROM uploaded_files WHERE id = %s", (file_id,))
                db.commit()
            if cursor.rowcount == 0:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "File not found"})
            else:
                self.send_json(HTTPStatus.OK, {"ok": True})
            return
        attachment_match = re.fullmatch(r"/api/admin/projects/(\d+)/attachments/(\d+)", urlparse(self.path).path)
        if attachment_match:
            project_id, attachment_id = map(int, attachment_match.groups())
            with connect_db() as db:
                row = db.execute("DELETE FROM project_attachments WHERE project_id = %s AND id = %s RETURNING file_id", (project_id, attachment_id)).fetchone()
                if row:
                    delete_file_if_unattached(db, row["file_id"])
            if row is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Attachment not found"})
            else:
                self.send_json(HTTPStatus.OK, {"ok": True})
            return
        match = re.fullmatch(r"/api/admin/(projects|certifications|activities)/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        table, item_id = match.group(1), int(match.group(2))
        file_column = "thumbnail_id" if table == "projects" else "certificate_file_id" if table == "certifications" else None
        with connect_db() as db:
            item = db.execute(f'SELECT "{file_column}" FROM "{table}" WHERE id = %s', (item_id,)).fetchone() if file_column else None
            file_id = item[file_column] if item else None
            attachment_file_ids = [row["file_id"] for row in db.execute("SELECT file_id FROM project_attachments WHERE project_id = %s", (item_id,)).fetchall()] if table == "projects" else []
            cursor = db.execute(f'DELETE FROM "{table}" WHERE id = %s', (item_id,))
            db.commit()
            delete_file_if_unattached(db, file_id)
            for attachment_file_id in attachment_file_ids:
                delete_file_if_unattached(db, attachment_file_id)
            db.commit()
        if cursor.rowcount == 0:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Entry not found"})
        else:
            self.send_json(HTTPStatus.OK, {"ok": True})

    def mutate_content(self, table: str, item_id: int | None) -> None:
        try:
            incoming = self.body_json()
            values: dict[str, object] = {}
            for name, kind in TABLES[table].items():
                value = incoming.get(name, "")
                if kind == "bool":
                    values[name] = bool(value)
                elif kind == "file":
                    if value in (None, ""):
                        values[name] = None
                    else:
                        file_id = int(value)
                        if file_id < 1:
                            raise ValueError(f"{name} is invalid")
                        values[name] = file_id
                else:
                    value = str(value).strip()
                    if len(value) > (2048 if kind == "url" else 8000):
                        raise ValueError(f"{name} is too long")
                    if kind == "url" and not validate_url(value):
                        raise ValueError(f"{name} must use http or https")
                    values[name] = value
            slug = None
            slug_was_supplied = False
            if table == "projects":
                requested_slug = str(incoming.get("slug", "")).strip()
                slug_was_supplied = bool(requested_slug)
                slug = slugify(requested_slug or str(values["title"]))
                if not slug:
                    raise ValueError("Project title must contain letters or numbers to create a slug")
            required = "title" if table == "projects" else "name"
            if not values.get(required):
                raise ValueError(f"{required} is required")
            published = bool(incoming.get("is_published"))
            sort_order = int(incoming.get("sort_order", 0))
            if abs(sort_order) > 1_000_000:
                raise ValueError("sort order is out of range")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error) or "Invalid request"})
            return
        if table == "projects":
            values["slug"] = slug
        columns = list(values)
        with connect_db() as db:
            for name, kind in TABLES[table].items():
                if kind == "file" and values[name] is not None:
                    file_record = db.execute("SELECT media_type FROM uploaded_files WHERE id = %s", (values[name],)).fetchone()
                    if file_record is None:
                        self.send_json(HTTPStatus.BAD_REQUEST, {"error": f"{name} refers to a file that does not exist"})
                        return
                    if table == "projects" and file_record["media_type"] not in {"image/png", "image/jpeg", "image/webp"}:
                        self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Thumbnail must be an image (PNG, JPG, JPEG, or WEBP)."})
                        return
            file_column = next((name for name, kind in TABLES[table].items() if kind == "file"), None)
            previous_file_id = None
            if table == "projects":
                if item_id is not None and not slug_was_supplied:
                    current = db.execute("SELECT slug FROM projects WHERE id = %s", (item_id,)).fetchone()
                    if current:
                        slug = current["slug"]
                        values["slug"] = slug
                if item_id is None and not slug_was_supplied:
                    base = slug
                    suffix = 2
                    while db.execute("SELECT 1 FROM projects WHERE slug = %s", (slug,)).fetchone():
                        tail = f"-{suffix}"
                        slug = f"{base[:160-len(tail)].rstrip('-')}{tail}"
                        suffix += 1
                    values["slug"] = slug
                    duplicate = None
                elif item_id is None:
                    duplicate = db.execute("SELECT id FROM projects WHERE slug = %s", (slug,)).fetchone()
                else:
                    duplicate = db.execute("SELECT id FROM projects WHERE slug = %s AND id <> %s", (slug, item_id)).fetchone()
                if duplicate:
                    self.send_json(HTTPStatus.CONFLICT, {"error": "That project slug is already in use"})
                    return
            if item_id is not None and file_column:
                existing = db.execute(f'SELECT "{file_column}" FROM "{table}" WHERE id = %s', (item_id,)).fetchone()
                previous_file_id = existing[file_column] if existing else None
            if item_id is None:
                names = columns + ["is_published", "sort_order"]
                placeholders = ", ".join("%s" for _ in names)
                cursor = db.execute(f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({placeholders}) RETURNING id', [values[key] for key in columns] + [published, sort_order])
                item_id = cursor.fetchone()["id"]
            else:
                assignments = [f'"{name}" = %s' for name in columns] + ["is_published = %s", "sort_order = %s", "updated_at = CURRENT_TIMESTAMP"]
                cursor = db.execute(f'UPDATE "{table}" SET {", ".join(assignments)} WHERE id = %s', [values[key] for key in columns] + [published, sort_order, item_id])
                if cursor.rowcount == 0:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Entry not found"})
                    return
            db.commit()
            if previous_file_id is not None and previous_file_id != values.get(file_column):
                delete_file_if_unattached(db, previous_file_id)
                db.commit()
            row = db.execute(f'SELECT * FROM "{table}" WHERE id = %s', (item_id,)).fetchone()
        self.send_json(HTTPStatus.OK if self.command == "PUT" else HTTPStatus.CREATED, dict(row))

    def do_PATCH(self) -> None:
        if not self.require_session():
            return
        match = re.fullmatch(r"/api/admin/(projects|certifications|activities)/(\d+)/order", urlparse(self.path).path)
        if not match:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        try:
            order = int(self.body_json().get("sort_order", 0))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError, TypeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid order"})
            return
        with connect_db() as db:
            cursor = db.execute(f'UPDATE "{match.group(1)}" SET sort_order = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s', (order, int(match.group(2))))
            db.commit()
        if cursor.rowcount == 0:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Entry not found"})
        else:
            self.send_json(HTTPStatus.OK, {"ok": True})

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def serve_static(self, requested_path: str) -> None:
        path = unquote(requested_path)
        if path in ("/", "/index.html"):
            file = ROOT / "index.html"
        elif path == "/admin":
            file = ROOT / "admin.html"
        elif path == "/about":
            file = ROOT / "about.html"
        elif re.fullmatch(r"/projects/[a-z0-9]+(?:-[a-z0-9]+)*", path):
            file = ROOT / "project.html"
        elif path in ("/styles.css", "/extra.css", "/contact-profile.css", "/script.js", "/admin.css", "/admin-extra.css", "/writeups-admin.css", "/profile-admin.css", "/admin.js", "/project.css", "/project-download.css", "/project.js", "/about.css", "/about.js"):
            file = ROOT / path.lstrip("/")
        elif path == "/assets/portfolio-hero.png":
            file = ASSET_ROOT / "portfolio-hero.png"
        else:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            body = file.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = "image/png" if file.suffix == ".png" else "text/css; charset=utf-8" if file.suffix == ".css" else "text/javascript; charset=utf-8" if file.suffix == ".js" else "text/html; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if path == "/admin":
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    init_db()
    print(f"Portfolio running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), PortfolioHandler).serve_forever()


if __name__ == "__main__":
    main()
