import os
import uuid
import json
import dashscope
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rag_engine import RAGEngine
from conversations import ConversationStore
from config import DASHSCOPE_API_KEY, LLM_MODEL, UPLOAD_DIR, USER_DATA_DIR
from auth import UserStore, CaptchaStore, LoginRateLimiter, AuthService, get_current_user


app = FastAPI(title="知识库问答系统")

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 引擎缓存（每个用户独立）
_engines: dict[str, RAGEngine] = {}

def get_engine(user_id: str = None) -> RAGEngine:
    key = user_id or "__global__"
    if key not in _engines:
        _engines[key] = RAGEngine(user_id)
    return _engines[key]

# 认证服务实例
user_store = UserStore()
captcha_store = CaptchaStore()
rate_limiter = LoginRateLimiter()


class ChatRequest(BaseModel):
    question: str
    conversation_id: str = None


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
async def register(phone: str = Form(...), password: str = Form(...)):
    user = user_store.register(phone, password)
    token = AuthService.create_token(user["id"], user["phone_masked"])
    return {"token": token, "user_id": user["id"], "phone_masked": user["phone_masked"]}


@app.get("/api/auth/captcha")
async def get_captcha():
    captcha_id, image_b64 = captcha_store.create()
    return {"captcha_id": captcha_id, "image": f"data:image/png;base64,{image_b64}"}


@app.post("/api/auth/login")
async def login(phone: str = Form(...), password: str = Form(...), captcha_id: str = Form(...), captcha_code: str = Form(...)):
    # 1. 检查是否锁定
    if rate_limiter.check_locked(phone):
        return {"error": "locked", "detail": "账号已锁定，请 1 小时后再试"}

    # 2. 验证验证码
    if not captcha_store.verify(captcha_id, captcha_code):
        return {"error": "captcha_wrong", "detail": "验证码错误"}

    # 3. 验证身份
    user_id = user_store.authenticate(phone, password)
    if user_id is None:
        result = rate_limiter.record_failure(phone)
        if result["locked"]:
            return {"error": "locked", "detail": "密码错误次数过多，账号已锁定 1 小时", "remaining_minutes": result["remaining_minutes"]}
        return {"error": "login_failed", "detail": f"手机号或密码错误，还剩 {result['remaining_attempts']} 次机会"}

    # 4. 成功
    rate_limiter.record_success(phone)
    user = user_store.get_user(user_id)
    token = AuthService.create_token(user_id, user["phone_masked"])
    return {"token": token, "user_id": user_id, "phone_masked": user["phone_masked"]}


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
    with open(file_path, "wb") as f:
        f.write(content)

    try:
        result = engine.process_pdf(file_path, doc_id, original_name=original_name)
        return result
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"PDF 处理失败：{str(e)}")


@app.get("/api/documents")
async def list_documents(user_id: str = Depends(get_current_user)):
    return get_engine(user_id).list_documents()


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, user_id: str = Depends(get_current_user)):
    success = get_engine(user_id).delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档未找到")
    return {"status": "deleted"}


@app.delete("/api/documents")
async def clear_documents(user_id: str = Depends(get_current_user)):
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

    result = get_engine(user_id).query(req.question)

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

    def generate():
        full_text = ""
        sources = []

        for msg_type, data in get_engine(user_id).stream_query(req.question):
            if msg_type == "sources":
                sources = data
                yield f"data: {json.dumps({'type': 'sources', 'data': data})}\n\n"
            elif msg_type == "token":
                full_text += data
                yield f"data: {json.dumps({'type': 'token', 'data': data})}\n\n"
            elif msg_type == "error":
                yield f"data: {json.dumps({'type': 'error', 'data': data})}\n\n"
                return

        if full_text:
            conv_store.add_message(conv_id, "assistant", full_text, sources)

        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
