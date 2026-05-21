import os
import re
import json
import uuid
import time
import hashlib
import secrets
import base64
import io
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import (
    DATA_DIR, USER_DATA_DIR, JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS,
    MAX_LOGIN_ATTEMPTS, LOCKOUT_HOURS, CAPTCHA_TTL_MINUTES,
)


# ===== 工具函数 =====

def _atomic_write(filepath: str, data: dict):
    """先写临时文件再 rename，防止写入中断导致文件损坏"""
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, filepath)


def _read_json(filepath: str, default: dict = None) -> dict:
    if default is None:
        default = {}
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _hash_phone(phone: str) -> str:
    """手机号单向哈希，用于索引（不用于安全验证）"""
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def _hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 密码哈希"""
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
    """138****1234"""
    return phone[:3] + "****" + phone[-4:]


# ===== 手机号验证 =====

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def validate_phone(phone: str):
    if not PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="手机号格式不正确")


# ===== 用户存储 =====

USERS_PATH = os.path.join(DATA_DIR, "users.json")


class UserStore:
    def register(self, phone: str, password: str) -> dict:
        validate_phone(phone)
        if len(password) < 6:
            raise HTTPException(status_code=422, detail="密码至少 6 位")

        os.makedirs(DATA_DIR, exist_ok=True)
        data = _read_json(USERS_PATH)

        # 检查手机号是否已注册
        phone_hash = _hash_phone(phone)
        for uid, info in data.get("users", {}).items():
            if info.get("phone_hash") == phone_hash:
                raise HTTPException(status_code=409, detail="该手机号已注册")

        user_id = str(uuid.uuid4())[:8]
        if "users" not in data:
            data["users"] = {}

        data["users"][user_id] = {
            "phone_hash": phone_hash,
            "password_hash": _hash_password(password),
            "phone_masked": _mask_phone(phone),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write(USERS_PATH, data)
        return {"id": user_id, "phone_masked": _mask_phone(phone)}

    def authenticate(self, phone: str, password: str) -> str | None:
        """验证用户凭据，成功返回 user_id，失败返回 None"""
        data = _read_json(USERS_PATH)
        phone_hash = _hash_phone(phone)
        for uid, info in data.get("users", {}).items():
            if info.get("phone_hash") == phone_hash:
                if _verify_password(password, info["password_hash"]):
                    return uid
                return None
        return None

    def get_user(self, user_id: str) -> dict | None:
        data = _read_json(USERS_PATH)
        return data.get("users", {}).get(user_id)


# ===== 图片验证码 =====

CAPTCHAS_PATH = os.path.join(DATA_DIR, "captchas.json")


class CaptchaStore:
    """生成和验证图片验证码"""

    def create(self) -> tuple[str, str]:
        """返回 (captcha_id, base64_image)"""
        os.makedirs(DATA_DIR, exist_ok=True)

        code = "".join(secrets.choice("0123456789") for _ in range(4))
        captcha_id = str(uuid.uuid4())[:8]
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=CAPTCHA_TTL_MINUTES)).isoformat()

        image_b64 = self._generate_image(code)

        data = _read_json(CAPTCHAS_PATH)
        data["captchas"] = data.get("captchas", {})
        data["captchas"][captcha_id] = {"code": code, "expires_at": expires_at}
        _atomic_write(CAPTCHAS_PATH, data)

        return captcha_id, image_b64

    def _generate_image(self, code: str) -> str:
        """生成 150×40 PNG 验证码图片（4 位数字），返回 base64"""
        width, height = 150, 40
        image = Image.new("RGB", (width, height), (245, 245, 245))
        draw = ImageDraw.Draw(image)

        # 随机干扰线
        for _ in range(3):
            x1 = secrets.randbelow(width)
            y1 = secrets.randbelow(height)
            x2 = secrets.randbelow(width)
            y2 = secrets.randbelow(height)
            draw.line([(x1, y1), (x2, y2)], fill=(180, 180, 180), width=1)

        # 尝试加载字体，失败则用默认
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except (IOError, OSError):
            font = ImageFont.load_default()

        # 逐个写入数字，每个有随机偏移和旋转
        char_images = []
        for ch in code:
            char_img = Image.new("RGBA", (28, 32), (0, 0, 0, 0))
            char_draw = ImageDraw.Draw(char_img)
            char_draw.text((4, 1), ch, fill=(50, 50, 50), font=font)
            angle = secrets.randbelow(40) - 20  # -20 ~ 20 度
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
        """验证验证码。一次有效，无论成功失败都消耗。"""
        data = _read_json(CAPTCHAS_PATH)
        captchas = data.get("captchas", {})

        entry = captchas.pop(captcha_id, None)
        _atomic_write(CAPTCHAS_PATH, data)

        if entry is None:
            return False

        expires_at = datetime.fromisoformat(entry["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            return False

        return entry["code"] == code.strip()


# ===== 登录频率限制 =====

ATTEMPTS_PATH = os.path.join(DATA_DIR, "login_attempts.json")


class LoginRateLimiter:
    def _get_key(self, phone: str) -> str:
        return _hash_phone(phone)

    def record_failure(self, phone: str) -> dict:
        """记录登录失败。返回 {locked, remaining_attempts, locked_until}"""
        data = _read_json(ATTEMPTS_PATH)
        key = self._get_key(phone)

        now = datetime.now(timezone.utc)
        entry = data.get("attempts", {}).get(key)

        if not entry:
            entry = {"count": 0, "first_attempt_at": now.isoformat(), "locked_until": None}

        # 检查是否已经锁定
        if entry.get("locked_until"):
            locked_until = datetime.fromisoformat(entry["locked_until"])
            if now < locked_until:
                remaining = int((locked_until - now).total_seconds() // 60)
                return {"locked": True, "remaining_attempts": 0, "locked_until": locked_until.isoformat(), "remaining_minutes": remaining}
            else:
                # 锁定过期，重置计数器但不删除（防止反复触发锁）
                entry = {"count": 0, "first_attempt_at": now.isoformat(), "locked_until": None}

        entry["count"] += 1

        if entry["count"] >= MAX_LOGIN_ATTEMPTS:
            locked_until = now + timedelta(hours=LOCKOUT_HOURS)
            entry["locked_until"] = locked_until.isoformat()

        data.setdefault("attempts", {})
        data["attempts"][key] = entry
        _atomic_write(ATTEMPTS_PATH, data)

        remaining = MAX_LOGIN_ATTEMPTS - entry["count"]
        return {
            "locked": bool(entry.get("locked_until")),
            "remaining_attempts": max(0, remaining),
            "locked_until": entry.get("locked_until"),
            "remaining_minutes": int(LOCKOUT_HOURS * 60) if entry.get("locked_until") else 0,
        }

    def record_success(self, phone: str):
        """登录成功，清除尝试记录"""
        data = _read_json(ATTEMPTS_PATH)
        key = self._get_key(phone)
        data.setdefault("attempts", {})
        data["attempts"].pop(key, None)
        _atomic_write(ATTEMPTS_PATH, data)

    def check_locked(self, phone: str) -> bool:
        data = _read_json(ATTEMPTS_PATH)
        key = self._get_key(phone)
        entry = data.get("attempts", {}).get(key)
        if entry and entry.get("locked_until"):
            locked_until = datetime.fromisoformat(entry["locked_until"])
            return datetime.now(timezone.utc) < locked_until
        return False


# ===== JWT 服务 =====

class AuthService:
    @staticmethod
    def create_token(user_id: str, phone_masked: str) -> str:
        payload = {
            "sub": user_id,
            "phone": phone_masked,
            "iat": int(time.time()),
            "exp": int(time.time()) + JWT_EXPIRY_HOURS * 3600,
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
    """从 JWT 中提取 user_id。所有需要认证的接口通过 Depends() 使用。"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    payload = AuthService.validate_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return payload["sub"]
