import os
import secrets
import hashlib
import base64
from dotenv import load_dotenv

load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

# Railway 有 /data 持久目录时就用它，否则用用户目录
# 可通过 DATA_DIR 环境变量强制指定
DATA_DIR = os.getenv("DATA_DIR") or (
    "/data" if os.path.exists("/data") else os.path.join(os.path.expanduser("~"), "ai-kb-data")
)

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")

# 用户数据隔离目录
USER_DATA_DIR = os.path.join(DATA_DIR, "user_data")

# 认证配置
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"

# 字段级加密密钥（用于手机号等敏感字段，可逆加密）
_field_key = hashlib.sha256(JWT_SECRET.encode()).digest()
FIELD_ENCRYPT_KEY = base64.urlsafe_b64encode(_field_key)
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "3"))
LOCKOUT_HOURS = int(os.getenv("LOCKOUT_HOURS", "1"))
CAPTCHA_TTL_MINUTES = int(os.getenv("CAPTCHA_TTL_MINUTES", "5"))

# 数据库：Railway 会自动注入 DATABASE_URL（PostgreSQL）
DATABASE_URL = os.getenv("DATABASE_URL", "")
