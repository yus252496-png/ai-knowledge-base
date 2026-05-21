import os
import secrets
from dotenv import load_dotenv

load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

# Railway 有 /data 持久目录时就用它，否则用用户目录
if os.path.exists("/data"):
    DATA_DIR = "/data/ai-kb-data"
else:
    DATA_DIR = os.path.join(os.path.expanduser("~"), "ai-kb-data")

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")

# 用户数据隔离目录
USER_DATA_DIR = os.path.join(DATA_DIR, "user_data")

# 认证配置
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "3"))
LOCKOUT_HOURS = int(os.getenv("LOCKOUT_HOURS", "1"))
CAPTCHA_TTL_MINUTES = int(os.getenv("CAPTCHA_TTL_MINUTES", "5"))
