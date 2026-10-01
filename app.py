"""Small web server and PostgreSQL API for the portfolio."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
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
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SESSION_SECRET = os.environ.get("APP_SECRET", "")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
MAX_BODY = 128 * 1024
SESSION_SECONDS = 60 * 60 * 8
PBKDF2_ROUNDS = 310_000

TABLES = {
    "projects": {
        "title": "text", "summary": "text", "description": "text",
        "tools": "text", "category": "text", "github_url": "url",
        "external_url": "url", "featured": "bool",
    },
    "certifications": {
        "name": "text", "issuer": "text", "date": "text",
        "credential_url": "url", "credential_id": "text", "description": "text",
    },
    "activities": {
        "name": "text", "role": "text", "start_date": "text",
        "end_date": "text", "description": "text", "url": "url",
    },
}
RATE_LIMITS: dict[str, list[float]] = {}
SESSIONS: dict[str, dict[str, object]] = {}


def connect_db() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required. Configure a PostgreSQL connection string in .env.")
    return psycopg.connect(DATABASE_URL, connect_timeout=10, row_factory=dict_row)


def init_db() -> None:
    if not SESSION_SECRET or SESSION_SECRET == "replace-with-a-long-random-secret":
        raise RuntimeError("Set APP_SECRET to a unique random value in .env before starting the server.")
    with connect_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS admins (
            id BIGSERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            salt BYTEA NOT NULL, password_hash BYTEA NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        for table, fields in TABLES.items():
            definitions = []
            for name, kind in fields.items():
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
        count = db.execute("SELECT COUNT(*) AS count FROM admins").fetchone()["count"]
        if count == 0 and ADMIN_EMAIL and ADMIN_PASSWORD:
            salt = secrets.token_bytes(16)
            digest = hashlib.pbkdf2_hmac("sha256", ADMIN_PASSWORD.encode(), salt, PBKDF2_ROUNDS)
            db.execute("INSERT INTO admins (email, salt, password_hash) VALUES (%s, %s, %s)", (ADMIN_EMAIL, salt, digest))
            print(f"Admin account initialized for {ADMIN_EMAIL}")
        activity_count = db.execute("SELECT COUNT(*) AS count FROM activities").fetchone()["count"]
        if activity_count == 0:
            db.execute("INSERT INTO activities (name, role, is_published, sort_order) VALUES (%s, %s, TRUE, 0)", ("BINUS Cyber Security Community", "Member"))


def json_bytes(value: object) -> bytes:
    def encode_extra(item: object) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"Cannot serialize {type(item).__name__}")

    return json.dumps(value, ensure_ascii=False, default=encode_extra).encode("utf-8")


def validate_url(value: str) -> bool:
    return not value or (len(value) <= 2048 and value.startswith(("https://", "http://")))


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
        data = SESSIONS.get(sid)
        if not data or not hmac.compare_digest(signature, expected) or float(data["expires"]) < time.time():
            SESSIONS.pop(sid, None)
            return None
        data["expires"] = time.time() + SESSION_SECONDS
        return data

    def require_session(self) -> dict[str, object] | None:
        current = self.session()
        if current is None:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Please sign in"})
            return None
        if self.command in ("POST", "PUT", "DELETE"):
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
        match = re.fullmatch(r"/api/public/(projects|certifications|activities)", parsed.path)
        if match:
            table = match.group(1)
            with connect_db() as db:
                rows = db.execute(f'SELECT * FROM "{table}" WHERE is_published IS TRUE ORDER BY sort_order, id DESC').fetchall()
            self.send_json(HTTPStatus.OK, [dict(row) for row in rows])
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
            match = re.fullmatch(r"/api/admin/(projects|certifications|activities)", parsed.path)
            if match:
                with connect_db() as db:
                    rows = db.execute(f'SELECT * FROM "{match.group(1)}" ORDER BY sort_order, id DESC').fetchall()
                self.send_json(HTTPStatus.OK, [dict(row) for row in rows])
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/admin/login":
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin and urlparse(origin).netloc != host:
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid request origin"})
                return
            ip = self.client_address[0]
            now = time.time()
            attempts = [stamp for stamp in RATE_LIMITS.get(ip, []) if now - stamp < 300]
            if len(attempts) >= 8:
                RATE_LIMITS[ip] = attempts
                self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Too many attempts. Try again in a few minutes."})
                return
            RATE_LIMITS[ip] = attempts + [now]
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
            SESSIONS[sid] = {"email": email, "csrf": csrf, "expires": now + SESSION_SECONDS}
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
            SESSIONS.pop(sid, None)
            secure = "; Secure" if COOKIE_SECURE else ""
            self.send_json(HTTPStatus.OK, {"ok": True}, f"portfolio=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{secure}")
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
        match = re.fullmatch(r"/api/admin/(projects|certifications|activities)/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        self.mutate_content(match.group(1), int(match.group(2)))

    def do_DELETE(self) -> None:
        if not self.require_session():
            return
        match = re.fullmatch(r"/api/admin/(projects|certifications|activities)/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        with connect_db() as db:
            cursor = db.execute(f'DELETE FROM "{match.group(1)}" WHERE id = %s', (int(match.group(2)),))
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
                else:
                    value = str(value).strip()
                    if len(value) > (2048 if kind == "url" else 8000):
                        raise ValueError(f"{name} is too long")
                    if kind == "url" and not validate_url(value):
                        raise ValueError(f"{name} must use http or https")
                    values[name] = value
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
        columns = list(values)
        with connect_db() as db:
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
        elif path in ("/styles.css", "/extra.css", "/script.js", "/admin.css", "/admin.js"):
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
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    init_db()
    print(f"Portfolio running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), PortfolioHandler).serve_forever()


if __name__ == "__main__":
    main()
