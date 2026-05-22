import os
import sqlite3
import threading
from contextlib import contextmanager
from config import DATA_DIR, DATABASE_URL

DATABASE_PATH = os.path.join(DATA_DIR, "ai_knowledge.db")
USE_PG = bool(DATABASE_URL and DATABASE_URL.startswith("postgres"))

_local = threading.local()


class DBConnection:
    """Unified connection wrapper for SQLite and PostgreSQL"""

    def __init__(self, conn):
        self._conn = conn
        self._pg = USE_PG

    def execute(self, sql, params=None):
        if self._pg:
            sql = sql.replace("?", "%s")
            cur = self._conn.cursor()
            cur.execute(sql, params or ())
            return cur
        return self._conn.execute(sql, params or ())

    def executescript(self, sql):
        if self._pg:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.upper().startswith("PRAGMA"):
                    self.execute(stmt)
        else:
            self._conn.executescript(sql)

    def insert_or_replace(self, table, pk_column, data: dict):
        """INSERT OR REPLACE for both SQLite and PostgreSQL"""
        cols = ", ".join(data.keys())
        vals = tuple(data.values())
        if self._pg:
            placeholders = ", ".join(["%s"] * len(data))
            updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in data if k != pk_column)
            sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT ({pk_column}) DO UPDATE SET {updates}"
            cur = self._conn.cursor()
            cur.execute(sql, vals)
            return cur
        else:
            placeholders = ", ".join(["?"] * len(data))
            sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
            return self._conn.execute(sql, vals)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def get_connection():
    if USE_PG:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    else:
        if not hasattr(_local, "conn") or _local.conn is None:
            _local.conn = sqlite3.connect(DATABASE_PATH)
            _local.conn.row_factory = sqlite3.Row
            _local.conn.execute("PRAGMA journal_mode=WAL")
            _local.conn.execute("PRAGMA foreign_keys=ON")
        return _local.conn


@contextmanager
def get_db():
    raw_conn = get_connection()
    conn = DBConnection(raw_conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if USE_PG:
            raw_conn.close()


def init_db():
    if USE_PG:
        _init_pg()
    else:
        _init_sqlite()


def _init_sqlite():
    os.makedirs(DATA_DIR, exist_ok=True)
    raw_conn = sqlite3.connect(DATABASE_PATH)
    raw_conn.row_factory = sqlite3.Row
    raw_conn.execute("PRAGMA journal_mode=WAL")
    raw_conn.execute("PRAGMA foreign_keys=ON")
    conn = DBConnection(raw_conn)
    _ddl_sqlite(conn)
    _migrate_sqlite(conn)
    conn.commit()
    raw_conn.close()


def _init_pg():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    raw_conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn = DBConnection(raw_conn)
    _ddl_pg(conn)
    conn.commit()
    raw_conn.close()


def _ddl_sqlite(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            phone_hash TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            phone_masked TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            security_question TEXT NOT NULL DEFAULT '',
            security_answer_hash TEXT NOT NULL DEFAULT '',
            security_answer TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user'
        );

        CREATE TABLE IF NOT EXISTS captchas (
            captcha_id TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            phone_hash TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0,
            first_attempt_at TEXT,
            locked_until TEXT
        );

        CREATE TABLE IF NOT EXISTS conversations (
            conv_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '新对话',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sources_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (conv_id) REFERENCES conversations(conv_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id);
        CREATE INDEX IF NOT EXISTS idx_captchas_expires ON captchas(expires_at);

        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT,
            user_id TEXT,
            file_name TEXT NOT NULL,
            total_pages INTEGER NOT NULL DEFAULT 0,
            total_chunks INTEGER NOT NULL DEFAULT 0,
            pdf_data BLOB,
            created_at TEXT NOT NULL,
            PRIMARY KEY (doc_id, user_id)
        );
    """)


def _ddl_pg(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            phone_hash TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            phone_masked TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            security_question TEXT NOT NULL DEFAULT '',
            security_answer_hash TEXT NOT NULL DEFAULT '',
            security_answer TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user'
        );

        CREATE TABLE IF NOT EXISTS captchas (
            captcha_id TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            phone_hash TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0,
            first_attempt_at TEXT,
            locked_until TEXT
        );

        CREATE TABLE IF NOT EXISTS conversations (
            conv_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '新对话',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            msg_id SERIAL PRIMARY KEY,
            conv_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sources_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (conv_id) REFERENCES conversations(conv_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id);
        CREATE INDEX IF NOT EXISTS idx_captchas_expires ON captchas(expires_at);

        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT,
            user_id TEXT,
            file_name TEXT NOT NULL,
            total_pages INTEGER NOT NULL DEFAULT 0,
            total_chunks INTEGER NOT NULL DEFAULT 0,
            pdf_data BYTEA,
            created_at TEXT NOT NULL,
            PRIMARY KEY (doc_id, user_id)
        );
    """)


def _migrate_sqlite(conn):
    """字段迁移：补充老数据库缺失的列"""
    import sqlite3 as _sqlite3
    for col in ("security_question", "security_answer_hash", "role", "phone", "security_answer"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        except _sqlite3.OperationalError:
            pass
    # 回填超级管理员手机号并加密
    conn.execute("UPDATE users SET phone = '17688939632' WHERE phone_masked = '176****9632' AND phone = ''")
    rows = conn.execute("SELECT user_id, phone FROM users WHERE phone != ''").fetchall()
    for r in rows:
        plain = r["phone"]
        if plain.startswith("gAAAA"):
            continue
        try:
            from auth import encrypt_field
            conn.execute("UPDATE users SET phone = ? WHERE user_id = ?", (encrypt_field(plain), r["user_id"]))
        except Exception:
            pass
