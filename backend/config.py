import os
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
