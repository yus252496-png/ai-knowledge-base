import os
import sqlite3
import threading
from contextlib import contextmanager
from config import DATA_DIR

DATABASE_PATH = os.path.join(DATA_DIR, "ai_knowledge.db")

_local = threading.local()


def get_connection():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DATABASE_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            phone_hash TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            phone_masked TEXT NOT NULL,
            created_at TEXT NOT NULL,
            security_question TEXT NOT NULL DEFAULT '',
            security_answer_hash TEXT NOT NULL DEFAULT ''
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
    """)
    conn.commit()

    # 迁移：为已有数据库补充 security 字段
    try:
        conn.execute("ALTER TABLE users ADD COLUMN security_question TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # 字段已存在
    try:
        conn.execute("ALTER TABLE users ADD COLUMN security_answer_hash TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # 字段已存在
    conn.commit()
