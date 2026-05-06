import base64
import binascii
import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "app.db"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-secret-change-this-before-production"
    )
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # 6MB

    if os.environ.get("RENDER_EXTERNAL_URL"):
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    init_db()

    @app.before_request
    def load_current_user() -> None:
        user_id = session.get("user_id")
        g.user = None
        if user_id:
            g.user = query_one(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,),
            )

    @app.route("/")
    def index():
        if g.user:
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            if len(username) < 3:
                flash("用户名至少 3 个字符。", "error")
                return render_template("register.html")
            if len(password) < 6:
                flash("密码至少 6 个字符。", "error")
                return render_template("register.html")

            existing = query_one(
                "SELECT id FROM users WHERE username = ?",
                (username,),
            )
            if existing:
                flash("用户名已存在，请换一个。", "error")
                return render_template("register.html")

            password_hash = generate_password_hash(password)
            execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (username, password_hash, utc_now()),
            )
            user = query_one("SELECT id FROM users WHERE username = ?", (username,))
            session["user_id"] = user["id"]
            flash("注册成功，欢迎使用超级粘贴板。", "success")
            return redirect(url_for("dashboard"))

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = query_one(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,),
            )
            if not user or not check_password_hash(user["password_hash"], password):
                flash("用户名或密码错误。", "error")
                return render_template("login.html")

            session["user_id"] = user["id"]
            flash("登录成功。", "success")
            return redirect(url_for("dashboard"))

        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        session.clear()
        flash("已退出登录。", "success")
        return redirect(url_for("index"))

    @app.route("/dashboard", methods=["GET", "POST"])
    @login_required
    def dashboard():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            cropped_image_data = request.form.get("cropped_image_data", "").strip()

            if not title:
                flash("标题不能为空。", "error")
                return redirect(url_for("dashboard"))

            image_path = save_base64_image(cropped_image_data)
            execute(
                """
                INSERT INTO clips (user_id, title, content, image_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (g.user["id"], title, content, image_path, utc_now(), utc_now()),
            )
            flash("内容已保存。", "success")
            return redirect(url_for("dashboard"))

        clips = query_all(
            """
            SELECT id, title, content, image_path, created_at, updated_at
            FROM clips
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (g.user["id"],),
        )
        return render_template("dashboard.html", clips=clips)

    @app.route("/clips/<int:clip_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_clip(clip_id: int):
        clip = query_one(
            """
            SELECT id, user_id, title, content, image_path, created_at, updated_at
            FROM clips
            WHERE id = ? AND user_id = ?
            """,
            (clip_id, g.user["id"]),
        )
        if not clip:
            flash("未找到该条目。", "error")
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            cropped_image_data = request.form.get("cropped_image_data", "").strip()
            keep_existing_image = request.form.get("keep_existing_image", "1")
            remove_existing_image = request.form.get("remove_existing_image", "0")

            if not title:
                flash("标题不能为空。", "error")
                return render_template("edit_clip.html", clip=clip)

            image_path = clip["image_path"] if keep_existing_image == "1" else None
            if remove_existing_image == "1":
                image_path = None
            new_image_path = save_base64_image(cropped_image_data)
            if new_image_path:
                image_path = new_image_path

            execute(
                """
                UPDATE clips
                SET title = ?, content = ?, image_path = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (title, content, image_path, utc_now(), clip_id, g.user["id"]),
            )
            flash("已更新内容。", "success")
            return redirect(url_for("dashboard"))

        return render_template("edit_clip.html", clip=clip)

    @app.route("/clips/<int:clip_id>/delete", methods=["POST"])
    @login_required
    def delete_clip(clip_id: int):
        execute(
            "DELETE FROM clips WHERE id = ? AND user_id = ?",
            (clip_id, g.user["id"]),
        )
        flash("已删除。", "success")
        return redirect(url_for("dashboard"))

    return app


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            image_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    conn.commit()
    conn.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    cursor = get_db().execute(sql, params)
    row = cursor.fetchone()
    cursor.close()
    return row


def query_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    cursor = get_db().execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def execute(sql: str, params: tuple = ()) -> None:
    db = get_db()
    db.execute(sql, params)
    db.commit()


def save_base64_image(data_url: str) -> str | None:
    if not data_url:
        return None
    if not data_url.startswith("data:image/"):
        return None

    try:
        header, encoded = data_url.split(",", 1)
    except ValueError:
        return None

    if "base64" not in header:
        return None

    ext = "png"
    if "image/jpeg" in header:
        ext = "jpg"
    elif "image/webp" in header:
        ext = "webp"

    filename = f"{uuid.uuid4().hex}.{ext}"
    file_path = UPLOAD_DIR / filename

    try:
        binary_data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None

    if len(binary_data) > 5 * 1024 * 1024:
        return None

    file_path.write_bytes(binary_data)
    return f"uploads/{filename}"


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("请先登录。", "error")
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


app = create_app()


@app.teardown_appcontext
def teardown_db(exception) -> None:  # noqa: ANN001
    db = g.pop("db", None)
    if db is not None:
        db.close()


if __name__ == "__main__":
    app.run(debug=True)
