import uuid
import json
from datetime import datetime
from typing import Optional
from database import get_db


class ConversationStore:
    def __init__(self, user_id: str = None):
        self.user_id = user_id

    def create(self, first_message: str = "") -> dict:
        conv_id = str(uuid.uuid4())[:8]
        title = first_message[:30] + "..." if len(first_message) > 30 else (first_message or "新对话")
        now = datetime.now().isoformat()

        with get_db() as db:
            db.execute(
                "INSERT INTO conversations (conv_id, user_id, title, created_at, updated_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
                (conv_id, self.user_id, title, now, now),
            )
            # 把其他会话的 is_active 设为 0
            db.execute(
                "UPDATE conversations SET is_active = 0 WHERE user_id = ? AND conv_id != ?",
                (self.user_id, conv_id),
            )

        return {"id": conv_id, "title": title, "created_at": now, "updated_at": now, "messages": []}

    def list_all(self) -> list:
        with get_db() as db:
            rows = db.execute(
                """SELECT conv_id, title, created_at, updated_at,
                          (SELECT COUNT(*) FROM messages WHERE conv_id = c.conv_id) AS message_count
                   FROM conversations c WHERE user_id = ? ORDER BY updated_at DESC""",
                (self.user_id,),
            ).fetchall()
        return [
            {
                "id": r["conv_id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "message_count": r["message_count"],
            }
            for r in rows
        ]

    def get(self, conv_id: str) -> Optional[dict]:
        with get_db() as db:
            conv = db.execute(
                "SELECT conv_id, title, created_at, updated_at FROM conversations WHERE conv_id = ? AND user_id = ?",
                (conv_id, self.user_id),
            ).fetchone()
            if conv is None:
                return None

            msgs = db.execute(
                "SELECT role, content, sources_json FROM messages WHERE conv_id = ? ORDER BY msg_id",
                (conv_id,),
            ).fetchall()

            # 设为 active
            db.execute("UPDATE conversations SET is_active = 0 WHERE user_id = ?", (self.user_id,))
            db.execute("UPDATE conversations SET is_active = 1 WHERE conv_id = ?", (conv_id,))

        return {
            "id": conv["conv_id"],
            "title": conv["title"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "messages": [
                {"role": m["role"], "content": m["content"], "sources": json.loads(m["sources_json"])}
                for m in msgs
            ],
        }

    def add_message(self, conv_id: str, role: str, content: str, sources: list = None):
        now = datetime.now().isoformat()
        sources_json = json.dumps(sources or [], ensure_ascii=False)

        with get_db() as db:
            db.execute(
                "UPDATE conversations SET updated_at = ?, title = CASE WHEN title = '新对话' AND ? = 'user' THEN ? ELSE title END WHERE conv_id = ?",
                (now, role, (content[:30] + "..." if len(content) > 30 else content), conv_id),
            )
            db.execute(
                "INSERT INTO messages (conv_id, role, content, sources_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (conv_id, role, content, sources_json, now),
            )

    def get_active(self) -> Optional[dict]:
        with get_db() as db:
            conv = db.execute(
                "SELECT conv_id FROM conversations WHERE user_id = ? AND is_active = 1",
                (self.user_id,),
            ).fetchone()
        if conv is None:
            return None
        return self.get(conv["conv_id"])

    def delete(self, conv_id: str) -> bool:
        with get_db() as db:
            conv = db.execute(
                "SELECT 1 FROM conversations WHERE conv_id = ? AND user_id = ?", (conv_id, self.user_id)
            ).fetchone()
            if conv is None:
                return False
            db.execute("DELETE FROM conversations WHERE conv_id = ?", (conv_id,))
        return True

    def get_or_create_active(self) -> dict:
        active = self.get_active()
        if active:
            return active
        return self.create()
