import os
import json
import uuid
from datetime import datetime
from typing import Optional
from config import DATA_DIR


class ConversationStore:
    def __init__(self):
        self.data_path = os.path.join(DATA_DIR, "conversations.json")
        os.makedirs(DATA_DIR, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.data_path):
            self._save({"conversations": {}, "active_id": None})

    def _load(self) -> dict:
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"conversations": {}, "active_id": None}

    def _save(self, data: dict):
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def create(self, first_message: str = "") -> dict:
        data = self._load()
        conv_id = str(uuid.uuid4())[:8]
        title = first_message[:30] + "..." if len(first_message) > 30 else (first_message or "新对话")
        now = datetime.now().isoformat()
        data["conversations"][conv_id] = {
            "id": conv_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        data["active_id"] = conv_id
        self._save(data)
        return data["conversations"][conv_id]

    def list_all(self) -> list:
        data = self._load()
        convs = data.get("conversations", {})
        result = []
        for cid, c in convs.items():
            result.append({
                "id": cid,
                "title": c.get("title", "新对话"),
                "created_at": c.get("created_at", ""),
                "updated_at": c.get("updated_at", ""),
                "message_count": len(c.get("messages", [])),
            })
        result.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return result

    def get(self, conv_id: str) -> Optional[dict]:
        data = self._load()
        conv = data.get("conversations", {}).get(conv_id)
        if conv:
            data["active_id"] = conv_id
            self._save(data)
        return conv

    def add_message(self, conv_id: str, role: str, content: str, sources: list = None):
        data = self._load()
        conv = data.get("conversations", {}).get(conv_id)
        if not conv:
            return None
        conv["messages"].append({
            "role": role,
            "content": content,
            "sources": sources or [],
        })
        conv["updated_at"] = datetime.now().isoformat()
        # 用第一条用户消息更新标题
        if role == "user" and conv["title"] == "新对话":
            conv["title"] = content[:30] + "..." if len(content) > 30 else content
        data["active_id"] = conv_id
        self._save(data)
        return conv["messages"][-1]

    def get_active(self) -> Optional[dict]:
        data = self._load()
        active_id = data.get("active_id")
        if active_id and active_id in data.get("conversations", {}):
            return data["conversations"][active_id]
        return None

    def set_active(self, conv_id: str):
        data = self._load()
        if conv_id in data.get("conversations", {}):
            data["active_id"] = conv_id
            self._save(data)

    def delete(self, conv_id: str) -> bool:
        data = self._load()
        if conv_id not in data.get("conversations", {}):
            return False
        del data["conversations"][conv_id]
        if data.get("active_id") == conv_id:
            data["active_id"] = None
        self._save(data)
        return True

    def get_or_create_active(self) -> dict:
        active = self.get_active()
        if active:
            return active
        return self.create()
