"""
datapilot_db.py - accounts, database and file storage for DataPilot AI
======================================================================
No Streamlit code in here, so it can be tested and reused (see tests/ and
migrate_sqlite_to_mysql.py).

Phase 1  Accounts      register / login / logout support, PBKDF2 password hashing,
                       lock-out after repeated wrong passwords, every query scoped to a user id.
Phase 2  MySQL         the same helper functions run on SQLite (default, zero setup) or MySQL.
Phase 3  File storage  datasets, original uploads and reports are stored with ownership checks,
                       atomic writes and SHA-256 integrity checks, on disk or inside the database.

Settings come from environment variables (see .env.example):
    DATAPILOT_DB            sqlite (default) | mysql
    MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
    DATAPILOT_HOME          folder for datapilot.db and datapilot_storage/ (default: next to this file)
    DATAPILOT_STORAGE       disk (default) | db   ("db" keeps files in the database: use it on hosts
                                                    whose disk is wiped on restart)
    DATAPILOT_CLAIM_LEGACY  1 (default) | 0       first new account takes over data from the old
                                                    no-login version of the app
"""

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# ----------------------------------------------------------------------
# Constants shared with the app
# ----------------------------------------------------------------------
SETTING_COLS = ("default_agg", "ppt_style", "kpi_cards", "dash_charts", "palette", "template")
THEME_KEYS = ("theme_name", "theme_bg", "theme_accent", "theme_solid", "look", "bg3d", "fx", "flex_dark")
DEFAULT_SETTINGS = dict(default_agg="sum", ppt_style="Dark (Power BI)", kpi_cards=4,
                        dash_charts=4, palette="Vivid", template="plotly_dark",
                        theme_name="Midnight Blue", theme_bg="#0a1024",
                        theme_accent="#00b4d8", theme_solid=False, look="Flex",
                        bg3d="Neural network", fx=True, flex_dark=True)
PBKDF2_ITER = 200_000
LEGACY_HASH = "!no-login"                      # account made by the old version without login
UPLOAD_EXTS = {"csv", "xlsx", "xlsm", "json", "db", "sqlite", "sqlite3"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STORAGE_ROOTS = ("datasets", "reports", "uploads")


class AuthError(ValueError):
    """A sign-up / sign-in problem whose message is safe to show to the user."""


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
CFG = {}


def configure(**overrides):
    """(Re)read the environment. Keyword arguments override it (used by tests)."""
    base = Path(os.environ.get("DATAPILOT_HOME") or Path(__file__).resolve().parent)
    CFG.clear()
    CFG.update(
        backend=(os.environ.get("DATAPILOT_DB") or "sqlite").strip().lower(),
        base_dir=base,
        db_path=base / "datapilot.db",
        storage=base / "datapilot_storage",
        storage_backend=(os.environ.get("DATAPILOT_STORAGE") or "disk").strip().lower(),
        claim_legacy=(os.environ.get("DATAPILOT_CLAIM_LEGACY") or "1") != "0",
        max_attempts=5,
        lock_minutes=15,
        mysql=dict(host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
                   port=int(os.environ.get("MYSQL_PORT") or 3306),
                   user=os.environ.get("MYSQL_USER", "datapilot"),
                   password=os.environ.get("MYSQL_PASSWORD", ""),
                   database=os.environ.get("MYSQL_DATABASE", "datapilot")),
    )
    for k, v in overrides.items():
        if k == "mysql":
            CFG["mysql"].update(v)
        else:
            CFG[k] = Path(v) if k in ("base_dir", "db_path", "storage") else v
    if CFG["backend"] not in ("sqlite", "mysql"):
        raise ValueError("DATAPILOT_DB must be 'sqlite' or 'mysql'.")
    if CFG["storage_backend"] not in ("disk", "db"):
        raise ValueError("DATAPILOT_STORAGE must be 'disk' or 'db'.")
    return CFG


configure()


def is_mysql():
    return CFG["backend"] == "mysql"


def backend_label():
    return (f"MySQL ({CFG['mysql']['host']}/{CFG['mysql']['database']})" if is_mysql()
            else "SQLite (local file)") + f" · files on {'database' if CFG['storage_backend'] == 'db' else 'disk'}"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------
# Connections (one code path for SQLite and MySQL)
# ----------------------------------------------------------------------
class _Row(dict):
    """MySQL row that works like sqlite3.Row: row['name'], row[0] and dict(row)."""

    def __getitem__(self, k):
        if isinstance(k, int):
            return list(self.values())[k]
        return super().__getitem__(k)


def _norm(v):
    return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v


def _translate(sql):
    """SQLite-style SQL (?, IS ?) -> MySQL (%s, <=>)."""
    sql = sql.replace("%", "%%")
    sql = re.sub(r"\bIS \?", "<=> ?", sql)
    return sql.replace("?", "%s")


class _Result:
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = cur.lastrowid
        self.rowcount = cur.rowcount

    def _wrap(self, r):
        return None if r is None else _Row({k: _norm(v) for k, v in r.items()})

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [self._wrap(r) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class _MyCon:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(_translate(sql), tuple(params))
        return _Result(cur)


@contextmanager
def db():
    """Open a connection, commit on success, roll back on error, always close."""
    if is_mysql():
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise RuntimeError("MySQL mode needs the PyMySQL package: python -m pip install PyMySQL "
                               "cryptography") from exc
        m = CFG["mysql"]
        raw = pymysql.connect(host=m["host"], port=m["port"], user=m["user"], password=m["password"],
                              database=m["database"], charset="utf8mb4", autocommit=False,
                              cursorclass=pymysql.cursors.DictCursor, connect_timeout=10)
        con = _MyCon(raw)
    else:
        CFG["db_path"].parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(CFG["db_path"], timeout=10)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        con = raw
    try:
        yield con
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------
def schema_statements(mysql):
    """All CREATE statements for the chosen database."""
    if mysql:
        PK, INT, VC, LT, DT, BLOB = "INT AUTO_INCREMENT PRIMARY KEY", "INT", "VARCHAR", "LONGTEXT", "DATETIME", "LONGBLOB"
        tail = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    else:
        PK, INT, VC, LT, DT, BLOB = "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER", "TEXT", "TEXT", "TEXT", "BLOB"
        tail = ""

    def v(n):
        return f"VARCHAR({n})" if mysql else "TEXT"

    def idx(name, table, cols):
        return None if mysql else f"CREATE INDEX IF NOT EXISTS {name} ON {table}({cols})"

    ci = "" if mysql else " COLLATE NOCASE"       # MySQL: case-insensitive via table collation
    inline = (lambda name, cols: f",\n    INDEX {name} ({cols})") if mysql else (lambda name, cols: "")
    S = [
        f"""CREATE TABLE IF NOT EXISTS users (
    id              {PK},
    username        {v(64)} NOT NULL{ci},
    email           {v(255)},
    password_hash   {v(255)} NOT NULL,
    created_at      {DT} NOT NULL,
    last_login      {DT} NULL,
    is_admin        {INT} NOT NULL DEFAULT 0,
    failed_attempts {INT} NOT NULL DEFAULT 0,
    locked_until    {DT} NULL,
    UNIQUE (username)
){tail}""",
        f"""CREATE TABLE IF NOT EXISTS projects (
    id           {PK},
    user_id      {INT} NOT NULL,
    name         {v(80)} NOT NULL,
    source_name  {v(255)},
    n_rows       {INT},
    n_cols       {INT},
    columns_json {LT},
    dataset_path {v(500)},
    created_at   {DT} NOT NULL,
    updated_at   {DT} NOT NULL,
    UNIQUE (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE{inline('idx_projects_user', 'user_id')}
){tail}""",
        f"""CREATE TABLE IF NOT EXISTS chat_messages (
    id         {PK},
    user_id    {INT} NOT NULL,
    project_id {INT},
    role       {v(16)} NOT NULL CHECK (role IN ('user', 'assistant')),
    content    {LT} NOT NULL,
    created_at {DT} NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE{inline('idx_chat_user_proj', 'user_id, project_id')}
){tail}""",
        f"""CREATE TABLE IF NOT EXISTS reports (
    id          {PK},
    user_id     {INT} NOT NULL,
    project_id  {INT},
    report_type {v(64)} NOT NULL,
    file_name   {v(255)} NOT NULL,
    file_path   {v(500)} NOT NULL,
    size_bytes  {INT},
    created_at  {DT} NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL{inline('idx_reports_user', 'user_id')}
){tail}""",
        f"""CREATE TABLE IF NOT EXISTS user_settings (
    user_id      {INT} NOT NULL PRIMARY KEY,
    default_agg  {v(32)},
    ppt_style    {v(64)},
    kpi_cards    {INT},
    dash_charts  {INT},
    palette      {v(64)},
    template     {v(64)},
    extra_json   {LT},
    updated_at   {DT},
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
){tail}""",
        f"""CREATE TABLE IF NOT EXISTS analysis_history (
    id            {PK},
    user_id       {INT} NOT NULL,
    project_id    {INT},
    cleaning_json {LT},
    kpis_json     {LT},
    insights_json {LT},
    result_json   {LT},
    created_at    {DT} NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE{inline('idx_analysis_user', 'user_id, project_id')}
){tail}""",
        # original files the user uploaded (CSV / Excel / JSON / SQLite)
        f"""CREATE TABLE IF NOT EXISTS uploads (
    id         {PK},
    user_id    {INT} NOT NULL,
    project_id {INT},
    file_name  {v(255)} NOT NULL,
    file_path  {v(500)} NOT NULL,
    size_bytes {INT},
    sha256     {v(64)},
    created_at {DT} NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE{inline('idx_uploads_user', 'user_id')}
){tail}""",
        # file bytes when DATAPILOT_STORAGE=db
        f"""CREATE TABLE IF NOT EXISTS file_store (
    path       {v(500)} NOT NULL PRIMARY KEY,
    user_id    {INT} NOT NULL,
    data       {BLOB} NOT NULL,
    size_bytes {INT},
    sha256     {v(64)},
    created_at {DT} NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE{inline('idx_filestore_user', 'user_id')}
){tail}""",
    ]
    if not mysql:
        S += [idx("idx_projects_user", "projects", "user_id"),
              idx("idx_chat_user_proj", "chat_messages", "user_id, project_id"),
              idx("idx_reports_user", "reports", "user_id"),
              idx("idx_analysis_user", "analysis_history", "user_id, project_id"),
              idx("idx_uploads_user", "uploads", "user_id"),
              idx("idx_filestore_user", "file_store", "user_id")]
    return [s for s in S if s]


def _columns(con, table):
    if is_mysql():
        rows = con.execute("SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
                           "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?", (table,)).fetchall()
        return [r["name"] for r in rows]
    return [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]


def init_db():
    """Create all tables and storage folders; upgrade databases made by older versions."""
    if CFG["storage_backend"] == "disk":
        CFG["storage"].mkdir(parents=True, exist_ok=True)
    with db() as con:
        for stmt in schema_statements(is_mysql()):
            con.execute(stmt)
        cols = _columns(con, "users")
        dt = "DATETIME" if is_mysql() else "TEXT"
        for col, ddl in (("is_admin", "INTEGER NOT NULL DEFAULT 0"),
                         ("failed_attempts", "INTEGER NOT NULL DEFAULT 0"),
                         ("locked_until", f"{dt} NULL")):
            if col not in cols:                                   # database made by an older version
                con.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        if not con.execute("SELECT 1 FROM users WHERE is_admin = 1").fetchone():
            first = con.execute("SELECT MIN(id) AS m FROM users").fetchone()
            if first and first["m"] is not None:
                con.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (first["m"],))


def _dumps(obj):
    return json.dumps(obj, default=str, ensure_ascii=False)


def _loads(text, fallback):
    try:
        return json.loads(text) if text else fallback
    except Exception:
        return fallback


def _safe_name(s):
    return re.sub(r"[^\w.\-]", "_", str(s))[:80] or "file"


# ----------------------------------------------------------------------
# Phase 1 - accounts
# ----------------------------------------------------------------------
def hash_password(password, iterations=PBKDF2_ITER):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password, stored):
    try:
        algo, it, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:                                              # includes the legacy '!no-login' marker
        return False


_DUMMY_HASH = hash_password("dummy-password-for-timing", 1000)


def check_password_rules(password, username=""):
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    if len(password) > 128:
        raise AuthError("Password must be at most 128 characters.")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise AuthError("Password must contain at least one letter and one number.")
    if username and password.lower() == username.lower():
        raise AuthError("Password must not be the same as the username.")


def _public_user(row):
    return dict(id=row["id"], username=row["username"], email=row["email"],
                is_admin=bool(row["is_admin"]), created_at=row["created_at"])


def get_user(uid):
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return _public_user(row) if row else None


def legacy_account_exists():
    """True when an account from the old no-login version still has no password."""
    if not CFG["claim_legacy"]:
        return False
    with db() as con:
        return con.execute("SELECT 1 FROM users WHERE password_hash = ?", (LEGACY_HASH,)).fetchone() is not None


def user_count():
    with db() as con:
        return con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def register_user(username, email, password):
    """Create an account (or take over the old no-login account). Returns the user dict."""
    username = (username or "").strip()
    email = (email or "").strip()
    if not USERNAME_RE.match(username):
        raise AuthError("Username must be 3-32 characters: letters, numbers, dot, dash or underscore.")
    if email and (len(email) > 255 or not EMAIL_RE.match(email)):
        raise AuthError("That email address does not look right.")
    check_password_rules(password or "", username)
    pw_hash = hash_password(password)
    with db() as con:
        legacy = None
        if CFG["claim_legacy"]:
            legacy = con.execute("SELECT id FROM users WHERE password_hash = ? ORDER BY id LIMIT 1",
                                 (LEGACY_HASH,)).fetchone()
        skip = legacy["id"] if legacy else 0
        if con.execute("SELECT 1 FROM users WHERE username = ? AND id <> ?", (username, skip)).fetchone():
            raise AuthError("That username is already taken.")
        if email and con.execute("SELECT 1 FROM users WHERE email = ? AND id <> ?", (email, skip)).fetchone():
            raise AuthError("An account with that email already exists.")
        if legacy:
            con.execute("UPDATE users SET username = ?, email = ?, password_hash = ?, failed_attempts = 0, "
                        "locked_until = NULL WHERE id = ?", (username, email or None, pw_hash, legacy["id"]))
            uid = legacy["id"]
        else:
            first = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
            cur = con.execute("INSERT INTO users (username, email, password_hash, created_at, is_admin) "
                              "VALUES (?, ?, ?, ?, ?)",
                              (username, email or None, pw_hash, _now(), 1 if first else 0))
            uid = cur.lastrowid
    user = get_user(uid)
    user["claimed_legacy"] = bool(legacy)
    return user


def authenticate(username, password):
    """Check a login. Locks the account for a while after repeated failures."""
    username = (username or "").strip()
    generic = AuthError("Incorrect username or password.")
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            verify_password(password or "", _DUMMY_HASH)           # same time as a real check
            raise generic
        locked = row["locked_until"]
        if locked and datetime.strptime(str(locked), "%Y-%m-%d %H:%M:%S") > datetime.now():
            mins = max(1, int((datetime.strptime(str(locked), "%Y-%m-%d %H:%M:%S")
                               - datetime.now()).total_seconds() // 60) + 1)
            raise AuthError(f"Too many failed attempts. Try again in about {mins} minute(s).")
        if not verify_password(password or "", row["password_hash"]):
            n = int(row["failed_attempts"] or 0) + 1
            if n >= CFG["max_attempts"]:
                until = (datetime.now() + timedelta(minutes=CFG["lock_minutes"])).strftime("%Y-%m-%d %H:%M:%S")
                con.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                            (until, row["id"]))
            else:
                con.execute("UPDATE users SET failed_attempts = ? WHERE id = ?", (n, row["id"]))
            con.raw.commit() if is_mysql() else con.commit()      # keep the counter even though we raise
            raise generic
        con.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = ? WHERE id = ?",
                    (_now(), row["id"]))
        return _public_user(row)


def change_password(uid, old_password, new_password):
    with db() as con:
        row = con.execute("SELECT username, password_hash FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None or not verify_password(old_password or "", row["password_hash"]):
            raise AuthError("Your current password is not correct.")
        check_password_rules(new_password or "", row["username"])
        con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), uid))


def delete_account(uid, password):
    """Delete the account and every project, report, upload and file it owns."""
    with db() as con:
        row = con.execute("SELECT password_hash FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None or not verify_password(password or "", row["password_hash"]):
            raise AuthError("Password is not correct.")
        con.execute("DELETE FROM users WHERE id = ?", (uid,))      # cascades to all the user's rows
    _remove_user_files(uid)


# ----------------------------------------------------------------------
# Phase 3 - file storage (disk or database) with ownership checks
# ----------------------------------------------------------------------
def _abs(rel):
    """Resolve a stored relative path and make sure it stays inside the storage folder."""
    root = CFG["storage"].resolve()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise ValueError("Invalid storage path.")
    return p


def _check_owner(uid, rel):
    """Allow only paths like  datasets|reports|uploads / user_<uid> / file  that belong to uid."""
    rel = str(rel).replace("\\", "/")
    parts = rel.split("/")
    if (len(parts) < 3 or parts[0] not in STORAGE_ROOTS or parts[1] != f"user_{int(uid)}"
            or any(p in ("", ".", "..") for p in parts)):
        raise PermissionError("You do not have access to this file.")
    return rel


def store_put(uid, rel, data):
    rel = _check_owner(uid, rel)
    data = bytes(data)
    if CFG["storage_backend"] == "db":
        digest = hashlib.sha256(data).hexdigest()
        with db() as con:
            con.execute("DELETE FROM file_store WHERE path = ? AND user_id = ?", (rel, uid))
            con.execute("INSERT INTO file_store (path, user_id, data, size_bytes, sha256, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (rel, uid, data, len(data), digest, _now()))
        return
    path = _abs(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")      # write fully, then swap in
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def store_get(uid, rel):
    rel = _check_owner(uid, rel)
    if CFG["storage_backend"] == "db":
        with db() as con:
            row = con.execute("SELECT data, sha256 FROM file_store WHERE path = ? AND user_id = ?",
                              (rel, uid)).fetchone()
        if row is None:
            raise FileNotFoundError("File not found.")
        data = bytes(row["data"])
        if row["sha256"] and hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise IOError("The stored file is damaged (checksum mismatch).")
        return data
    return _abs(rel).read_bytes()


def store_delete(uid, rel):
    try:
        rel = _check_owner(uid, rel)
    except PermissionError:
        return
    if CFG["storage_backend"] == "db":
        with db() as con:
            con.execute("DELETE FROM file_store WHERE path = ? AND user_id = ?", (rel, uid))
        return
    try:
        _abs(rel).unlink(missing_ok=True)
    except Exception:
        pass


def _remove_user_files(uid):
    if CFG["storage_backend"] == "db":
        with db() as con:
            con.execute("DELETE FROM file_store WHERE user_id = ?", (uid,))
    for sub in STORAGE_ROOTS:
        try:
            shutil.rmtree(_abs(f"{sub}/user_{int(uid)}"), ignore_errors=True)
        except Exception:
            pass


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
def get_settings(uid):
    s = dict(DEFAULT_SETTINGS)
    with db() as con:
        row = con.execute("SELECT * FROM user_settings WHERE user_id = ?", (uid,)).fetchone()
    if row:
        for k in SETTING_COLS:
            if row[k] is not None:
                s[k] = row[k]
        extra = _loads(row["extra_json"], {})
        s.update({k: v for k, v in extra.items() if k in THEME_KEYS})
    return s


def save_settings(uid, s):
    extra = _dumps({k: s[k] for k in THEME_KEYS if k in s})
    vals = (s["default_agg"], s["ppt_style"], int(s["kpi_cards"]), int(s["dash_charts"]),
            s["palette"], s["template"], extra, _now())
    with db() as con:
        if con.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (uid,)).fetchone():
            con.execute("UPDATE user_settings SET default_agg = ?, ppt_style = ?, kpi_cards = ?, "
                        "dash_charts = ?, palette = ?, template = ?, extra_json = ?, updated_at = ? "
                        "WHERE user_id = ?", vals + (uid,))
        else:
            con.execute("INSERT INTO user_settings (user_id, default_agg, ppt_style, kpi_cards, dash_charts, "
                        "palette, template, extra_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (uid,) + vals)


# ----------------------------------------------------------------------
# Projects
# ----------------------------------------------------------------------
def _own_project(con, uid, pid):
    """Return pid only if it is a real project of this user, otherwise None."""
    if pid and con.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (pid, uid)).fetchone():
        return pid
    return None


def save_project(uid, name, source_name, df):
    """Create (or update, if the name already exists) a project and save its cleaned data."""
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("Please type a project name.")
    cols = [dict(name=str(c), dtype=str(t)) for c, t in df.dtypes.items()]
    created = False
    with db() as con:
        row = con.execute("SELECT id FROM projects WHERE user_id = ? AND name = ?", (uid, name)).fetchone()
        if row:
            pid = row["id"]
            con.execute("UPDATE projects SET source_name = ?, n_rows = ?, n_cols = ?, columns_json = ?, "
                        "updated_at = ? WHERE id = ?",
                        (source_name, len(df), len(df.columns), _dumps(cols), _now(), pid))
        else:
            cur = con.execute("INSERT INTO projects (user_id, name, source_name, n_rows, n_cols, columns_json, "
                              "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                              (uid, name, source_name, len(df), len(df.columns), _dumps(cols), _now(), _now()))
            pid, created = cur.lastrowid, True
    rel = f"datasets/user_{int(uid)}/project_{pid}.csv"
    try:
        store_put(uid, rel, df.to_csv(index=False).encode("utf-8"))
        with db() as con:
            con.execute("UPDATE projects SET dataset_path = ? WHERE id = ?", (rel, pid))
    except Exception:
        if created:                                                  # do not leave a project without data
            with db() as con:
                con.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (pid, uid))
        raise
    return pid


def list_projects(uid):
    with db() as con:
        rows = con.execute("SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                           (uid,)).fetchall()
    return [dict(r) for r in rows]


def load_project(uid, pid):
    """Return (project_row, DataFrame) for a project that belongs to this user."""
    with db() as con:
        row = con.execute("SELECT * FROM projects WHERE id = ? AND user_id = ?", (pid, uid)).fetchone()
    if row is None or not row["dataset_path"]:
        raise FileNotFoundError("Project not found.")
    return dict(row), pd.read_csv(io.BytesIO(store_get(uid, row["dataset_path"])))


def delete_project(uid, pid):
    with db() as con:
        row = con.execute("SELECT dataset_path FROM projects WHERE id = ? AND user_id = ?", (pid, uid)).fetchone()
        ups = con.execute("SELECT file_path FROM uploads WHERE project_id = ? AND user_id = ?",
                          (pid, uid)).fetchall()
        con.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (pid, uid))
    if row and row["dataset_path"]:
        store_delete(uid, row["dataset_path"])
    for u in ups:
        store_delete(uid, u["file_path"])


# ----------------------------------------------------------------------
# Original uploaded files
# ----------------------------------------------------------------------
def save_upload(uid, pid, filename, data):
    ext = str(filename).lower().rsplit(".", 1)[-1] if "." in str(filename) else ""
    if ext not in UPLOAD_EXTS:
        raise ValueError(f"Files of type '.{ext}' cannot be stored.")
    with db() as con:
        pid = _own_project(con, uid, pid)
        old = con.execute("SELECT id, file_path FROM uploads WHERE user_id = ? AND project_id IS ? "
                          "AND file_name = ?", (uid, pid, str(filename)[:255])).fetchall()
    rel = f"uploads/user_{int(uid)}/{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}_{_safe_name(filename)}"
    store_put(uid, rel, data)
    digest = hashlib.sha256(bytes(data)).hexdigest()
    with db() as con:
        cur = con.execute("INSERT INTO uploads (user_id, project_id, file_name, file_path, size_bytes, sha256, "
                          "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (uid, pid, str(filename)[:255], rel, len(data), digest, _now()))
        new_id = cur.lastrowid
        for o in old:                                                # a re-save replaces the earlier copy
            con.execute("DELETE FROM uploads WHERE id = ? AND user_id = ?", (o["id"], uid))
    for o in old:
        store_delete(uid, o["file_path"])
    return new_id


def list_uploads(uid, limit=50):
    with db() as con:
        rows = con.execute("SELECT u.*, p.name AS project_name FROM uploads u LEFT JOIN projects p "
                           "ON p.id = u.project_id WHERE u.user_id = ? ORDER BY u.id DESC LIMIT ?",
                           (uid, limit)).fetchall()
    return [dict(r) for r in rows]


def read_upload(uid, upload_id):
    """Return (row, bytes). Only the owner can read; the checksum is verified."""
    with db() as con:
        row = con.execute("SELECT * FROM uploads WHERE id = ? AND user_id = ?", (upload_id, uid)).fetchone()
    if row is None:
        raise FileNotFoundError("Upload not found.")
    data = store_get(uid, row["file_path"])
    if row["sha256"] and hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise IOError("The stored file is damaged (checksum mismatch).")
    return dict(row), data


def delete_upload(uid, upload_id):
    with db() as con:
        row = con.execute("SELECT file_path FROM uploads WHERE id = ? AND user_id = ?", (upload_id, uid)).fetchone()
        con.execute("DELETE FROM uploads WHERE id = ? AND user_id = ?", (upload_id, uid))
    if row:
        store_delete(uid, row["file_path"])


# ----------------------------------------------------------------------
# Analysis history and chat
# ----------------------------------------------------------------------
def add_analysis(uid, pid, cleaning_notes, kpis, insights, result):
    with db() as con:
        con.execute("INSERT INTO analysis_history (user_id, project_id, cleaning_json, kpis_json, insights_json, "
                    "result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, _own_project(con, uid, pid), _dumps(cleaning_notes), _dumps(kpis),
                     _dumps(insights), _dumps(result), _now()))


def list_analysis(uid, limit=50):
    with db() as con:
        rows = con.execute("SELECT a.*, p.name AS project_name FROM analysis_history a "
                           "LEFT JOIN projects p ON p.id = a.project_id WHERE a.user_id = ? "
                           "ORDER BY a.id DESC LIMIT ?", (uid, limit)).fetchall()
    return [dict(id=r["id"], project=r["project_name"] or "(unsaved)", created_at=r["created_at"],
                 cleaning=_loads(r["cleaning_json"], []), kpis=_loads(r["kpis_json"], []),
                 insights=_loads(r["insights_json"], []), result=_loads(r["result_json"], {})) for r in rows]


def add_chat(uid, pid, role, content):
    with db() as con:
        con.execute("INSERT INTO chat_messages (user_id, project_id, role, content, created_at) "
                    "VALUES (?, ?, ?, ?, ?)", (uid, _own_project(con, uid, pid), role, content, _now()))


def get_chat(uid, pid, limit=30):
    with db() as con:
        pid = _own_project(con, uid, pid)          # someone else's project id reads as 'unsaved data'
        rows = con.execute("SELECT role, content, created_at FROM chat_messages "
                           "WHERE user_id = ? AND project_id IS ? ORDER BY id DESC LIMIT ?",
                           (uid, pid, limit)).fetchall()
    return [dict(r) for r in rows][::-1]


def clear_chat(uid, pid):
    with db() as con:
        pid = _own_project(con, uid, pid)
        con.execute("DELETE FROM chat_messages WHERE user_id = ? AND project_id IS ?", (uid, pid))


# ----------------------------------------------------------------------
# Reports
# ----------------------------------------------------------------------
def save_report(uid, pid, report_type, filename, data):
    rel = f"reports/user_{int(uid)}/{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}_{_safe_name(filename)}"
    store_put(uid, rel, data)
    try:
        with db() as con:
            con.execute("INSERT INTO reports (user_id, project_id, report_type, file_name, file_path, "
                        "size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (uid, _own_project(con, uid, pid), report_type, str(filename)[:255], rel,
                         len(data), _now()))
    except Exception:
        store_delete(uid, rel)
        raise


def list_reports(uid, limit=15):
    with db() as con:
        rows = con.execute("SELECT r.*, p.name AS project_name FROM reports r LEFT JOIN projects p "
                           "ON p.id = r.project_id WHERE r.user_id = ? ORDER BY r.id DESC LIMIT ?",
                           (uid, limit)).fetchall()
    return [dict(r) for r in rows]


def read_report(uid, r):
    """Bytes of a report row, or None if it is missing or not yours."""
    try:
        if int(r.get("user_id", uid)) != int(uid):
            return None
        return store_get(uid, r["file_path"])
    except Exception:
        return None


def delete_report(uid, rid):
    with db() as con:
        row = con.execute("SELECT file_path FROM reports WHERE id = ? AND user_id = ?", (rid, uid)).fetchone()
        con.execute("DELETE FROM reports WHERE id = ? AND user_id = ?", (rid, uid))
    if row:
        store_delete(uid, row["file_path"])


# ----------------------------------------------------------------------
# Counts and clean-up
# ----------------------------------------------------------------------
def db_counts(uid):
    with db() as con:
        return {t: con.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE user_id = ?", (uid,)).fetchone()["n"]
                for t in ("projects", "reports", "chat_messages", "analysis_history", "uploads")}


def clear_all_data(uid):
    """Delete every saved project, report, upload, chat and analysis (account and settings are kept)."""
    with db() as con:
        for t in ("projects", "reports", "uploads", "chat_messages", "analysis_history"):
            con.execute(f"DELETE FROM {t} WHERE user_id = ?", (uid,))
    _remove_user_files(uid)


# ----------------------------------------------------------------------
# Phase 2 - move an existing SQLite database into MySQL
# ----------------------------------------------------------------------
MIGRATE_TABLES = ("users", "projects", "chat_messages", "reports", "user_settings", "analysis_history", "uploads")


def migrate_sqlite_to_mysql(sqlite_path, source_storage=None, log=print):
    """Copy every row (keeping ids) from an old datapilot.db into the configured MySQL database.
    The target must be empty. Files: if DATAPILOT_STORAGE=db they are copied into the database;
    with disk storage, point DATAPILOT_HOME at the same folder and nothing needs copying."""
    if not is_mysql():
        raise RuntimeError("Set DATAPILOT_DB=mysql (and the MYSQL_* variables) before migrating.")
    if not Path(sqlite_path).exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")
    init_db()
    if user_count():
        raise RuntimeError("The MySQL database already has users. Migrate into an empty database.")
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    copied = {}
    try:
        with db() as con:
            for t in MIGRATE_TABLES:
                if t not in have:
                    continue
                cols_src = [r["name"] for r in src.execute(f"PRAGMA table_info({t})")]
                cols = [c for c in cols_src if c in _columns(con, t)]
                rows = src.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall()
                for r in rows:
                    con.execute(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                tuple(r[c] for c in cols))
                copied[t] = len(rows)
                log(f"  {t}: {len(rows)} rows")
    finally:
        src.close()
    if CFG["storage_backend"] == "db":
        root = Path(source_storage) if source_storage else CFG["storage"]
        n = 0
        for f in root.rglob("*") if root.exists() else []:
            if f.is_file():
                rel = f.relative_to(root).as_posix()
                m = re.match(r"^(?:datasets|reports|uploads)/user_(\d+)/", rel)
                if m:
                    store_put(int(m.group(1)), rel, f.read_bytes())
                    n += 1
        copied["files"] = n
        log(f"  files copied into the database: {n}")
    return copied
