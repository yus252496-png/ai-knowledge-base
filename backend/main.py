import os
import uuid
import json
import threading
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rag_engine import RAGEngine
from conversations import ConversationStore
from config import UPLOAD_DIR, USER_DATA_DIR
from auth import user_store, captcha_store, rate_limiter, AuthService, get_current_user, get_current_admin, SECURITY_QUESTIONS, SUPER_ADMIN_PHONE, _hash_phone
from database import init_db, USE_PG
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 确保超级管理员 17688939632 拥有 super_admin 角色
    phone_hash = _hash_phone(SUPER_ADMIN_PHONE)
    user = user_store.get_by_phone_hash(phone_hash)
    if user:
        user_store.set_role(user["id"], "super_admin")
    # 回填已有用户的 security_answer_hash（兼容旧数据）
    from database import get_db
    try:
        with get_db() as db:
            rows = db.execute(
                "SELECT phone_hash, security_answer FROM users WHERE security_answer_hash = '' AND security_answer != ''"
            ).fetchall()
            for r in rows:
                h = _hash_phone(r["security_answer"].strip().lower())
                db.execute("UPDATE users SET security_answer_hash = ? WHERE phone_hash = ?", (h, r["phone_hash"]))
            if rows:
                print(f"已回填 {len(rows)} 个用户的密保答案 hash")
    except Exception as e:
        print(f"密保答案回填失败（非关键错误）：{e}")

    # 预热嵌入模型，避免首次请求触发同步下载阻塞事件循环
    try:
        from rag_engine import _LocalEmbeddings
        print("正在预热嵌入模型...")
        emb = _LocalEmbeddings()
        emb.embed_query("warmup")
        print("嵌入模型预热完成")
    except Exception as e:
        print(f"嵌入模型预热失败（非关键错误）：{e}")

    # 检测 LLM API 可达性
    try:
        from httpx import Client
        from config import LLM_BASE_URL, LLM_API_KEY
        c = Client(timeout=5)
        r = c.get(f"{LLM_BASE_URL}/models", headers={"Authorization": f"Bearer {LLM_API_KEY}"})
        print(f"LLM API 连通性检测: {r.status_code}")
        c.close()
    except Exception as e:
        print(f"LLM API 连通性检测失败（非关键错误）：{e}")

    yield


app = FastAPI(title="知识库问答系统", lifespan=lifespan)

# 限制上传文件最大 20MB（后端二次校验）
MAX_FILE_SIZE = 20 * 1024 * 1024


# 全局异常处理，返回具体错误信息
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "traceback": traceback.format_exc().split("\n")[-5:]},
    )


frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url, "http://localhost:5173", "http://localhost:3000", "https://www.elaik.cn"],
    allow_origin_regex=r"https://.*\.(vercel\.app|elaik\.cn)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 引擎缓存（每个用户独立）
_engines: dict[str, RAGEngine] = {}
_engine_locks: dict[str, threading.Lock] = {}

def get_engine(user_id: str = None) -> RAGEngine:
    key = user_id or "__global__"
    if key not in _engines:
        _engines[key] = RAGEngine(user_id)
    return _engines[key]

def _get_engine_lock(user_id: str) -> threading.Lock:
    """每个用户独立的 FAISS 写入锁，防止并发索引竞争"""
    key = user_id or "__global__"
    if key not in _engine_locks:
        _engine_locks[key] = threading.Lock()
    return _engine_locks[key]

# ===== 认证服务实例已移到 auth.py =====


class ChatRequest(BaseModel):
    question: str
    conversation_id: str = None
    doc_ids: Optional[List[str]] = None


class ChatResponse(BaseModel):
    answer: str
    sources: list
    conversation_id: str = None


# ===== 健康检查（公开） =====

@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ===== 认证模块 =====

@app.post("/api/auth/register")
async def register(phone: str = Form(...), password: str = Form(...), security_question: str = Form(...), security_answer: str = Form(...)):
    user = user_store.register(phone, password, security_question, security_answer)
    token = AuthService.create_token(user["id"], user["phone_masked"])
    return {"token": token, "user_id": user["id"], "phone_masked": user["phone_masked"], "role": "user"}


@app.get("/api/auth/security-questions")
async def get_security_questions():
    return {"questions": SECURITY_QUESTIONS}


@app.post("/api/auth/forgot-password")
async def forgot_password(phone: str = Form(...)):
    """第一步：验证手机号是否存在，返回密保问题"""
    user = user_store.get_user_by_phone(phone)
    if user is None:
        return {"error": "not_found", "detail": "该手机号未注册"}
    if not user.get("security_question"):
        return {"error": "no_security", "detail": "该账号未设置密保问题"}
    return {
        "phone_masked": user["phone_masked"],
        "security_question": user["security_question"],
    }


@app.post("/api/auth/verify-security")
async def verify_security(phone: str = Form(...), answer: str = Form(...)):
    """第二步：验证密保答案，返回重置令牌"""
    if not user_store.verify_security_answer(phone, answer):
        return {"error": "wrong_answer", "detail": "密保答案错误"}

    phone_hash = _hash_phone(phone)
    reset_token = AuthService.create_reset_token(phone_hash)
    return {"reset_token": reset_token}


@app.post("/api/auth/reset-password")
async def reset_password(reset_token: str = Form(...), new_password: str = Form(...)):
    """第三步：用重置令牌修改密码"""
    payload = AuthService.validate_token(reset_token)
    if payload is None or payload.get("type") != "reset":
        raise HTTPException(status_code=400, detail="重置链接已过期或无效")

    phone_hash = payload["phone_hash"]
    user_store.reset_password_by_hash(phone_hash, new_password)
    return {"status": "ok", "detail": "密码已重置"}


@app.get("/api/auth/captcha")
def get_captcha():
    captcha_id, image_b64 = captcha_store.create()
    return {"captcha_id": captcha_id, "image": f"data:image/png;base64,{image_b64}"}


@app.post("/api/auth/login")
def login(phone: str = Form(...), password: str = Form(...), captcha_id: str = Form(...), captcha_code: str = Form(...)):
    # 1. 检查是否锁定
    if rate_limiter.check_locked(phone):
        return {"error": "locked", "detail": "账号已锁定，请 1 小时后再试"}

    # 2. 验证验证码
    if not captcha_store.verify(captcha_id, captcha_code):
        return {"error": "captcha_wrong", "detail": "验证码错误"}

    # 3. 验证身份
    user_id = user_store.authenticate(phone, password)
    if user_id is None:
        return {"error": "not_registered", "detail": "该手机号未注册，请先注册"}
    if user_id is False:
        result = rate_limiter.record_failure(phone)
        if result["locked"]:
            return {"error": "locked", "detail": "密码错误次数过多，账号已锁定 1 小时", "remaining_minutes": result["remaining_minutes"]}
        return {"error": "login_failed", "detail": f"密码错误，还剩 {result['remaining_attempts']} 次机会"}

    # 4. 成功
    rate_limiter.record_success(phone)
    user = user_store.get_user_detail(user_id)
    role = user["role"] if user else "user"
    token = AuthService.create_token(user_id, user["phone_masked"], role)
    return {"token": token, "user_id": user_id, "phone_masked": user["phone_masked"], "role": role}


@app.get("/api/auth/me")
async def get_me(user_id: str = Depends(get_current_user)):
    user = user_store.get_user_detail(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "user_id": user["id"],
        "phone_masked": user["phone_masked"],
        "role": user["role"],
    }


# ===== 文档管理（需要认证） =====

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), user_id: str = Depends(get_current_user)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    doc_id = str(uuid.uuid4())[:8]
    safe_filename = f"{doc_id}.pdf"
    engine = get_engine(user_id)
    file_path = os.path.join(engine.upload_dir, safe_filename)
    original_name = file.filename

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件超过 20MB 限制，当前文件大小：{len(content) / 1024 / 1024:.1f}MB")

    with open(file_path, "wb") as f:
        f.write(content)

    # 1. 先保存元数据和 PDF 到 PG（立即持久化）
    meta = engine._load_metadata()
    meta["documents"][doc_id] = {
        "file_name": original_name,
        "total_pages": 0,
        "total_chunks": 0,
    }
    engine._save_metadata(meta)
    engine._pg_save_pdf(doc_id, content)

    # 2. 后台处理 FAISS 索引（可能耗时较长，避免 Railway 30s 超时）
    lock = _get_engine_lock(user_id)

    def _bg_process():
        with lock:
            try:
                bg_engine = RAGEngine(user_id)
                bg_engine.process_pdf(file_path, doc_id, original_name=original_name, pdf_bytes=content)
                # 直接将新 store 换入缓存引擎，无需等磁盘重载
                cached = _engines.get(user_id)
                if cached and bg_engine._store:
                    cached._store = bg_engine._store
            except Exception as e:
                import traceback
                print(f"后台索引失败 {doc_id}: {e}")
                traceback.print_exc()

    t = threading.Thread(target=_bg_process, daemon=True)
    t.start()

    return {"doc_id": doc_id, "file_name": original_name, "status": "processing"}


@app.get("/api/documents")
async def list_documents(user_id: str = Depends(get_current_user)):
    return get_engine(user_id).list_documents()


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user_id: str = Depends(get_current_user)):
    success = get_engine(user_id).delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档未找到")
    return {"status": "deleted"}


@app.delete("/api/documents")
def clear_documents(user_id: str = Depends(get_current_user)):
    get_engine(user_id).clear_documents()
    return {"status": "cleared"}


# ===== 聊天（需要认证） =====

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user)):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    conv_id = req.conversation_id
    conv_store = ConversationStore(user_id)
    if conv_id:
        conv = conv_store.get(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conv = conv_store.get_or_create_active()
        conv_id = conv["id"]

    conv_store.add_message(conv_id, "user", req.question)

    result = get_engine(user_id).query(req.question, doc_ids=req.doc_ids)

    conv_store.add_message(conv_id, "assistant", result["answer"], result["sources"])

    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        conversation_id=conv_id,
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, user_id: str = Depends(get_current_user)):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    conv_id = req.conversation_id
    conv_store = ConversationStore(user_id)
    if conv_id:
        conv = conv_store.get(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conv = conv_store.get_or_create_active()
        conv_id = conv["id"]

    conv_store.add_message(conv_id, "user", req.question)

    async def generate():
        import time as _time
        _t0 = _time.time()
        print(f"[stream] connected event at t={_t0:.1f}")
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"

        full_text = ""
        sources = []

        try:
            engine = get_engine(user_id)
            print(f"[stream] got engine at t={_time.time()-_t0:.1f}s, starting astream_query")
            async for msg_type, data in engine.astream_query(req.question, doc_ids=req.doc_ids):
                if msg_type == "sources":
                    sources = data
                    yield f"data: {json.dumps({'type': 'sources', 'data': data})}\n\n"
                elif msg_type == "token":
                    full_text += data
                    yield f"data: {json.dumps({'type': 'token', 'data': data})}\n\n"
                elif msg_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'data': data})}\n\n"
                    return
            print(f"[stream] LLM done at t={_time.time()-_t0:.1f}s")
        except Exception as e:
            print(f"[stream] ERROR: {e}")
            yield f"data: {json.dumps({'type': 'error', 'data': f'服务器内部错误：{e}'})}\n\n"
            return

        if full_text:
            conv_store.add_message(conv_id, "assistant", full_text, sources)
        print(f"[stream] done at t={_time.time()-_t0:.1f}s")
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
        },
    )


# ===== 会话管理（需要认证） =====

@app.post("/api/conversations")
async def create_conversation(user_id: str = Depends(get_current_user)):
    conv = ConversationStore(user_id).create()
    return conv


@app.get("/api/conversations")
async def list_conversations(user_id: str = Depends(get_current_user)):
    return ConversationStore(user_id).list_all()


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str, user_id: str = Depends(get_current_user)):
    conv = ConversationStore(user_id).get(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user_id: str = Depends(get_current_user)):
    conv_store = ConversationStore(user_id)
    success = conv_store.delete(conv_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "deleted"}


@app.get("/api/conversations/active/latest")
async def get_active_conversation(user_id: str = Depends(get_current_user)):
    conv = ConversationStore(user_id).get_or_create_active()
    return conv


# ===== 管理后台（需要管理员权限） =====

@app.get("/api/admin/users")
async def admin_list_users(search: str = "", admin_id: str = Depends(get_current_admin)):
    return user_store.list_users(search.strip())


@app.get("/api/admin/users/{target_id}")
async def admin_get_user(target_id: str, admin_id: str = Depends(get_current_admin)):
    user = user_store.get_user_detail(target_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 获取该用户的上传文件（优先从本地，备选从 PG）
    user_chroma_dir = os.path.join(USER_DATA_DIR, target_id, "chroma_db")
    meta_path = os.path.join(user_chroma_dir, "metadata.json")
    files = []
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            files = [
                {
                    "doc_id": doc_id,
                    "file_name": info.get("file_name", doc_id),
                    "total_pages": info.get("total_pages", 0),
                    "total_chunks": info.get("total_chunks", 0),
                }
                for doc_id, info in meta.get("documents", {}).items()
            ]
        except (json.JSONDecodeError, OSError):
            pass
    # 本地没有时从 PG 恢复
    if not files:
        try:
            from database import get_db
            with get_db() as db:
                rows = db.execute(
                    "SELECT doc_id, file_name, total_pages, total_chunks FROM documents WHERE user_id = ?",
                    (target_id,),
                ).fetchall()
            files = [
                {
                    "doc_id": r["doc_id"],
                    "file_name": r["file_name"],
                    "total_pages": r["total_pages"],
                    "total_chunks": r["total_chunks"],
                }
                for r in rows
            ]
        except Exception:
            pass

    # 获取该用户的对话历史
    conversations = ConversationStore(target_id).list_all()

    return {
        "user": user,
        "files": files,
        "conversations": conversations,
    }


@app.put("/api/admin/users/{target_id}")
async def admin_update_user(target_id: str, data: dict, admin_id: str = Depends(get_current_admin)):
    user_store.update_user(target_id, data)
    return {"status": "updated"}


@app.delete("/api/admin/users/{target_id}")
async def admin_delete_user(target_id: str, admin_id: str = Depends(get_current_admin)):
    if target_id == admin_id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    target_role = user_store.get_role(target_id)
    if target_role == "super_admin":
        raise HTTPException(status_code=403, detail="不能删除超级管理员")
    success = user_store.delete_user(target_id)
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"status": "deleted"}


@app.post("/api/admin/users/{target_id}/role")
async def admin_set_role(target_id: str, role: str = Form(...), admin_id: str = Depends(get_current_admin)):
    """只有超级管理员可以修改角色"""
    admin_role = user_store.get_role(admin_id)
    if admin_role != "super_admin":
        raise HTTPException(status_code=403, detail="只有超级管理员可以授权")
    if role not in ("user", "admin"):
        raise HTTPException(status_code=422, detail="只能设置为 user 或 admin")
    user_store.set_role(target_id, role)
    return {"status": "ok", "role": role}


@app.get("/api/admin/files/{target_id}/{doc_id}")
async def admin_serve_file(target_id: str, doc_id: str, admin_id: str = Depends(get_current_admin)):
    """提供 PDF 文件预览（浏览器内嵌），本地没有时从 PG 恢复"""
    file_path = os.path.join(USER_DATA_DIR, target_id, "uploads", f"{doc_id}.pdf")
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="application/pdf", filename=f"{doc_id}.pdf")
    # 尝试从 PG 恢复
    try:
        from database import get_db
        with get_db() as db:
            row = db.execute(
                "SELECT pdf_data FROM documents WHERE doc_id = ? AND user_id = ?",
                (doc_id, target_id),
            ).fetchone()
        if row and row["pdf_data"]:
            pdf_bytes = row["pdf_data"]
            if isinstance(pdf_bytes, memoryview):
                pdf_bytes = bytes(pdf_bytes)
            from fastapi.responses import Response
            return Response(content=pdf_bytes, media_type="application/pdf")
    except Exception as e:
        print(f"从 PG 恢复 PDF 预览失败：{e}")
    raise HTTPException(status_code=404, detail="文件不存在")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ===== 存储诊断（调试用） =====

@app.get("/api/debug/storage")
async def debug_storage():
    import config as cfg
    result = {
        "data_dir": cfg.DATA_DIR,
        "data_dir_exists": os.path.exists(cfg.DATA_DIR),
        "root_data_exists": os.path.exists("/data"),
        "db_path": os.path.join(cfg.DATA_DIR, "ai_knowledge.db"),
        "db_exists": os.path.exists(os.path.join(cfg.DATA_DIR, "ai_knowledge.db")),
        "cwd": os.getcwd(),
        "data_dir_contents": [],
    }
    if os.path.exists(cfg.DATA_DIR):
        try:
            result["data_dir_contents"] = os.listdir(cfg.DATA_DIR)
        except PermissionError:
            result["data_dir_contents"] = ["<permission denied>"]
    if os.path.exists("/data") and "/data" != cfg.DATA_DIR:
        try:
            result["root_data_contents"] = os.listdir("/data")
        except PermissionError:
            result["root_data_contents"] = ["<permission denied>"]
    return result


@app.get("/api/debug/db")
async def debug_db():
    """测试数据库连接（不需要认证）"""
    from database import get_db
    try:
        with get_db() as db:
            db.execute("SELECT 1")
            if USE_PG:
                rows = db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()
            else:
                rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            tables = [list(r.values())[0] for r in rows] if rows else []
        from config import DATABASE_URL
        return {"status": "ok", "use_pg": USE_PG, "has_database_url": bool(DATABASE_URL), "tables": tables}
    except Exception as e:
        import traceback
        from config import DATABASE_URL
        return {"status": "error", "use_pg": USE_PG, "has_database_url": bool(DATABASE_URL), "error": str(e), "traceback": traceback.format_exc().split("\n")[-5:]}


# ===== 解锁账号（临时调试用） =====

@app.post("/api/debug/unlock")
async def debug_unlock(phone: str = Form(...)):
    from database import get_db
    from auth import _hash_phone
    with get_db() as db:
        db.execute("DELETE FROM login_attempts WHERE phone_hash = ?", (_hash_phone(phone),))
    return {"status": "ok", "phone": phone}


# ===== FAISS 诊断 =====

@app.get("/api/debug/faiss")
async def debug_faiss(user_id: str = Depends(get_current_user)):
    """检查当前用户的 FAISS 索引状态"""
    engine = get_engine(user_id)
    store = engine._get_store()
    index_path = os.path.join(engine.chroma_dir, "index.faiss")
    meta = engine._load_metadata()
    doc_count = len(meta.get("documents", {}))
    return {
        "index_exists": os.path.exists(index_path),
        "chroma_dir": engine.chroma_dir,
        "upload_dir": engine.upload_dir,
        "documents_in_metadata": doc_count,
        "documents_in_pg": doc_count,
        "pdf_files_on_disk": len([f for f in os.listdir(engine.upload_dir) if f.endswith(".pdf")]) if os.path.exists(engine.upload_dir) else 0,
    }
