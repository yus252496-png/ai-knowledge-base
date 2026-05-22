import re
import uuid
import time
import hashlib
import secrets
import base64
import io
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from PIL import Image, ImageDraw, ImageFont
from cryptography.fernet import Fernet

from config import (
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS,
    MAX_LOGIN_ATTEMPTS, LOCKOUT_HOURS, CAPTCHA_TTL_MINUTES, FIELD_ENCRYPT_KEY,
)
from database import get_db


# ===== 字段级加密（可逆） =====

_fernet = Fernet(FIELD_ENCRYPT_KEY)


def encrypt_field(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_field(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        return value  # 兼容未加密的旧数据


# ===== 工具函数 =====

def _hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, dk_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
        return dk.hex() == dk_hex
    except (ValueError, AttributeError):
        return False


def _mask_phone(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:]


# ===== 手机号验证 =====

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def validate_phone(phone: str):
    if not PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="手机号格式不正确")


# ===== 超级管理员手机号 =====

SUPER_ADMIN_PHONE = "17688939632"


# ===== 密保问题 =====

SECURITY_QUESTIONS = [
    "你的出生城市是？",
    "你的小学名称是？",
    "你最喜欢的食物是？",
    "你的宠物名字是？",
    "你母亲的姓名是？",
]

FORGOT_PASSWORD_EXPIRY = 300  # 5 分钟


# ===== 用户存储 =====

class UserStore:
    def register(self, phone: str, password: str, security_question: str, security_answer: str) -> dict:
        validate_phone(phone)
        if len(password) < 6:
            raise HTTPException(status_code=422, detail="密码至少 6 位")
        if security_question not in SECURITY_QUESTIONS:
            raise HTTPException(status_code=422, detail="无效的密保问题")
        if len(security_answer.strip()) < 1:
            raise HTTPException(status_code=422, detail="密保答案不能为空")

        phone_hash = _hash_phone(phone)
        answer_hash = _hash_phone(security_answer.strip().lower())

        with get_db() as db:
            existing = db.execute(
                "SELECT 1 FROM users WHERE phone_hash = ?", (phone_hash,)
            ).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="该手机号已注册")

            user_id = str(uuid.uuid4())[:8]
            db.execute(
                "INSERT INTO users (user_id, phone_hash, password_hash, phone_masked, phone, created_at, security_question, security_answer_hash, security_answer) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, phone_hash, _hash_password(password), _mask_phone(phone), encrypt_field(phone), datetime.now(timezone.utc).isoformat(), security_question, answer_hash, security_answer.strip()),
            )

        return {"id": user_id, "phone_masked": _mask_phone(phone)}

    def authenticate(self, phone: str, password: str) -> str | None | bool:
        phone_hash = _hash_phone(phone)
        with get_db() as db:
            row = db.execute(
                "SELECT user_id, password_hash FROM users WHERE phone_hash = ?", (phone_hash,)
            ).fetchone()
        if row is None:
            return None  # 手机号未注册
        if _verify_password(password, row["password_hash"]):
            return row["user_id"]  # 成功
        return False  # 密码错误

    def get_user(self, user_id: str) -> dict | None:
        with get_db() as db:
            row = db.execute(
                "SELECT user_id, phone_masked, phone_hash, created_at FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["user_id"],
            "phone_masked": row["phone_masked"],
            "phone_hash": row["phone_hash"],
            "created_at": row["created_at"],
        }

    def get_user_by_phone(self, phone: str) -> dict | None:
        """通过手机号查找用户，返回用户信息（不含密码）"""
        phone_hash = _hash_phone(phone)
        with get_db() as db:
            row = db.execute(
                "SELECT user_id, phone_masked, security_question FROM users WHERE phone_hash = ?",
                (phone_hash,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["user_id"],
            "phone_masked": row["phone_masked"],
            "security_question": row["security_question"],
        }

    def verify_security_answer(self, phone: str, answer: str) -> bool:
        """验证密保答案（兼容旧数据：hash 验证失败时尝试明文匹配）"""
        phone_hash = _hash_phone(phone)
        answer_hash = _hash_phone(answer.strip().lower())
        with get_db() as db:
            row = db.execute(
                "SELECT security_answer_hash, security_answer FROM users WHERE phone_hash = ?",
                (phone_hash,),
            ).fetchone()
        if row is None:
            return False
        # 优先 hash 比对
        if row["security_answer_hash"] and row["security_answer_hash"] == answer_hash:
            return True
        # 兼容旧数据：security_answer_hash 为空时回退到明文比对
        if not row["security_answer_hash"] and row["security_answer"]:
            if row["security_answer"].strip().lower() == answer.strip().lower():
                # 回填 hash
                with get_db() as db:
                    db.execute(
                        "UPDATE users SET security_answer_hash = ? WHERE phone_hash = ?",
                        (answer_hash, phone_hash),
                    )
                return True
        return False

    def update_password(self, phone: str, new_password: str):
        """更新密码"""
        if len(new_password) < 6:
            raise HTTPException(status_code=422, detail="密码至少 6 位")
        phone_hash = _hash_phone(phone)
        with get_db() as db:
            db.execute(
                "UPDATE users SET password_hash = ? WHERE phone_hash = ?",
                (_hash_password(new_password), phone_hash),
            )
            # 清除登录尝试记录
            db.execute("DELETE FROM login_attempts WHERE phone_hash = ?", (phone_hash,))

    def reset_password_by_hash(self, phone_hash: str, new_password: str):
        """通过 phone_hash 重置密码（用于忘记密码流程）"""
        if len(new_password) < 6:
            raise HTTPException(status_code=422, detail="密码至少 6 位")
        with get_db() as db:
            db.execute(
                "UPDATE users SET password_hash = ? WHERE phone_hash = ?",
                (_hash_password(new_password), phone_hash),
            )
            db.execute("DELETE FROM login_attempts WHERE phone_hash = ?", (phone_hash,))

    # ===== 管理员方法 =====

    def get_role(self, user_id: str) -> str:
        with get_db() as db:
            row = db.execute(
                "SELECT role FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["role"] if row else "user"

    def set_role(self, user_id: str, role: str):
        if role not in ("user", "admin", "super_admin"):
            raise HTTPException(status_code=422, detail="无效的角色")
        with get_db() as db:
            db.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))

    def list_users(self, search: str = "") -> list[dict]:
        with get_db() as db:
            rows = db.execute(
                "SELECT user_id, phone_masked, phone, role, created_at, security_question, security_answer FROM users ORDER BY created_at DESC"
            ).fetchall()
        result = []
        for r in rows:
            phone = decrypt_field(r["phone"]) or r["phone_masked"]
            if search and search not in phone:
                continue
            result.append({
                "id": r["user_id"],
                "phone": phone,
                "phone_masked": r["phone_masked"],
                "role": r["role"],
                "created_at": r["created_at"],
                "security_question": r["security_question"],
                "security_answer": r["security_answer"] or "",
            })
        return result

    def get_user_detail(self, user_id: str) -> dict | None:
        with get_db() as db:
            row = db.execute(
                "SELECT user_id, phone_masked, phone, role, created_at, security_question, security_answer FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["user_id"],
            "phone": decrypt_field(row["phone"]) or row["phone_masked"],
            "phone_masked": row["phone_masked"],
            "role": row["role"],
            "created_at": row["created_at"],
            "security_question": row["security_question"],
            "security_answer": row["security_answer"] or "",
        }

    def update_user(self, user_id: str, data: dict):
        fields = []
        values = []
        if "phone" in data:
            fields.append("phone = ?")
            values.append(encrypt_field(data["phone"]))
            fields.append("phone_masked = ?")
            values.append(_mask_phone(data["phone"]))
        if "security_question" in data:
            fields.append("security_question = ?")
            values.append(data["security_question"])
            if "security_answer" in data:
                fields.append("security_answer = ?")
                values.append(data["security_answer"])
                fields.append("security_answer_hash = ?")
                values.append(_hash_phone(data["security_answer"].strip().lower()))
        if "password" in data and data["password"]:
            fields.append("password_hash = ?")
            values.append(_hash_password(data["password"]))
        if not fields:
            return
        values.append(user_id)
        with get_db() as db:
            db.execute(f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?", values)

    def delete_user(self, user_id: str) -> bool:
        with get_db() as db:
            cur = db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0

    def get_by_phone_hash(self, phone_hash: str) -> dict | None:
        with get_db() as db:
            row = db.execute(
                "SELECT user_id, phone_masked, role FROM users WHERE phone_hash = ?", (phone_hash,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["user_id"],
            "phone_masked": row["phone_masked"],
            "role": row["role"],
        }


# ===== 图片验证码 =====

class CaptchaStore:
    def create(self) -> tuple[str, str]:
        code = "".join(secrets.choice("0123456789") for _ in range(4))
        captcha_id = str(uuid.uuid4())[:8]
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=CAPTCHA_TTL_MINUTES)).isoformat()

        image_b64 = self._generate_image(code)

        with get_db() as db:
            db.execute(
                "INSERT INTO captchas (captcha_id, code, expires_at) VALUES (?, ?, ?)",
                (captcha_id, code, expires_at),
            )

        return captcha_id, image_b64

    def _generate_image(self, code: str) -> str:
        width, height = 180, 50
        image = Image.new("RGB", (width, height), (245, 245, 245))
        draw = ImageDraw.Draw(image)

        for _ in range(4):
            x1 = secrets.randbelow(width)
            y1 = secrets.randbelow(height)
            x2 = secrets.randbelow(width)
            y2 = secrets.randbelow(height)
            draw.line([(x1, y1), (x2, y2)], fill=(180, 180, 180), width=1)

        _font_path = os.path.join(os.path.dirname(__file__), "DejaVuSans-Bold.ttf")
        try:
            font = ImageFont.truetype(_font_path, 32)
        except (IOError, OSError):
            try:
                font = ImageFont.truetype("arial.ttf", 32)
            except (IOError, OSError):
                font = ImageFont.load_default(size=28)

        char_images = []
        for ch in code:
            char_img = Image.new("RGBA", (32, 36), (0, 0, 0, 0))
            char_draw = ImageDraw.Draw(char_img)
            char_draw.text((4, 1), ch, fill=(50, 50, 50), font=font)
            angle = secrets.randbelow(30) - 15
            rotated = char_img.rotate(angle, expand=1, fillcolor=(0, 0, 0, 0))
            char_images.append(rotated)

        total_width = sum(c.width for c in char_images) + 12
        x_offset = max(8, (width - total_width) // 2)
        for cimg in char_images:
            image.paste(cimg, (x_offset, (height - cimg.height) // 2), cimg)
            x_offset += cimg.width + secrets.randbelow(3)

        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode()

    def verify(self, captcha_id: str, code: str) -> bool:
        with get_db() as db:
            row = db.execute(
                "SELECT code, expires_at FROM captchas WHERE captcha_id = ?", (captcha_id,)
            ).fetchone()
            db.execute("DELETE FROM captchas WHERE captcha_id = ?", (captcha_id,))

        if row is None:
            return False

        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            return False

        return row["code"] == code.strip()


# ===== 登录频率限制 =====

class LoginRateLimiter:
    def record_failure(self, phone: str) -> dict:
        phone_hash = _hash_phone(phone)
        now = datetime.now(timezone.utc)

        with get_db() as db:
            row = db.execute(
                "SELECT count, first_attempt_at, locked_until FROM login_attempts WHERE phone_hash = ?",
                (phone_hash,),
            ).fetchone()

            count = 0
            first_attempt_at = now.isoformat()
            locked_until = None

            if row:
                # 检查是否在锁定中
                if row["locked_until"]:
                    lu = datetime.fromisoformat(row["locked_until"])
                    if now < lu:
                        remaining = int((lu - now).total_seconds() // 60)
                        return {
                            "locked": True, "remaining_attempts": 0,
                            "locked_until": row["locked_until"],
                            "remaining_minutes": remaining,
                        }
                    # 锁定已过期，重置
                    count = 0
                    first_attempt_at = now.isoformat()
                    locked_until = None
                else:
                    count = row["count"]
                    first_attempt_at = row["first_attempt_at"]

            count += 1

            if count >= MAX_LOGIN_ATTEMPTS:
                locked_until = (now + timedelta(hours=LOCKOUT_HOURS)).isoformat()

            db.insert_or_replace("login_attempts", "phone_hash", {
                "phone_hash": phone_hash,
                "count": count,
                "first_attempt_at": first_attempt_at,
                "locked_until": locked_until,
            })

        return {
            "locked": locked_until is not None,
            "remaining_attempts": max(0, MAX_LOGIN_ATTEMPTS - count),
            "locked_until": locked_until,
            "remaining_minutes": int(LOCKOUT_HOURS * 60) if locked_until else 0,
        }

    def record_success(self, phone: str):
        phone_hash = _hash_phone(phone)
        with get_db() as db:
            db.execute("DELETE FROM login_attempts WHERE phone_hash = ?", (phone_hash,))

    def check_locked(self, phone: str) -> bool:
        phone_hash = _hash_phone(phone)
        with get_db() as db:
            row = db.execute(
                "SELECT locked_until FROM login_attempts WHERE phone_hash = ?", (phone_hash,)
            ).fetchone()
        if row and row["locked_until"]:
            return datetime.now(timezone.utc) < datetime.fromisoformat(row["locked_until"])
        return False


# ===== JWT 服务 =====

class AuthService:
    @staticmethod
    def create_token(user_id: str, phone_masked: str, role: str = "user") -> str:
        payload = {
            "sub": user_id,
            "phone": phone_masked,
            "role": role,
            "iat": int(time.time()),
            "exp": int(time.time()) + JWT_EXPIRY_HOURS * 3600,
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    @staticmethod
    def create_reset_token(phone_hash: str) -> str:
        """生成短时密保重置令牌（5 分钟有效）"""
        payload = {
            "type": "reset",
            "phone_hash": phone_hash,
            "iat": int(time.time()),
            "exp": int(time.time()) + FORGOT_PASSWORD_EXPIRY,
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    @staticmethod
    def validate_token(token: str) -> dict | None:
        try:
            return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None


# ===== FastAPI 依赖 =====

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    payload = AuthService.validate_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return payload["sub"]


async def get_current_admin(user_id: str = Depends(get_current_user)) -> str:
    """需要管理员或超级管理员权限"""
    role = user_store.get_role(user_id)
    if role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user_id


# 全局实例
user_store = UserStore()
captcha_store = CaptchaStore()
rate_limiter = LoginRateLimiter()
