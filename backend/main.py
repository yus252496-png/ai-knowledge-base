import os
import uuid
import json
import dashscope
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rag_engine import RAGEngine
from conversations import ConversationStore
from config import DASHSCOPE_API_KEY, LLM_MODEL, UPLOAD_DIR


app = FastAPI(title="知识库问答系统")

# CORS：开发环境允许本地，生产环境通过 FRONTEND_URL 环境变量配置
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(UPLOAD_DIR, exist_ok=True)

engine = None
conv_store = ConversationStore()


def get_engine():
    global engine
    if engine is None:
        engine = RAGEngine()
    return engine


class ChatRequest(BaseModel):
    question: str
    conversation_id: str = None


class ChatResponse(BaseModel):
    answer: str
    sources: list
    conversation_id: str = None


# ===== 健康检查 =====

@app.get("/api/health")
async def health():
    return {"status": "ok", "engine_ready": engine is not None}


# ===== 文档管理 =====

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    doc_id = str(uuid.uuid4())[:8]
    safe_filename = f"{doc_id}.pdf"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    original_name = file.filename

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    try:
        result = get_engine().process_pdf(file_path, doc_id, original_name=original_name)
        return result
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"PDF 处理失败：{str(e)}")


@app.get("/api/documents")
async def list_documents():
    return get_engine().list_documents()


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    success = get_engine().delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档未找到")
    return {"status": "deleted"}


@app.delete("/api/documents")
async def clear_documents():
    get_engine().clear_documents()
    return {"status": "cleared"}


# ===== 聊天 =====

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 获取或创建会话
    conv_id = req.conversation_id
    if conv_id:
        conv = conv_store.get(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conv = conv_store.get_or_create_active()
        conv_id = conv["id"]

    # 保存用户消息
    conv_store.add_message(conv_id, "user", req.question)

    # 调用 RAG
    result = get_engine().query(req.question)

    # 保存回答
    conv_store.add_message(conv_id, "assistant", result["answer"], result["sources"])

    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        conversation_id=conv_id,
    )


# ===== 流式聊天（SSE） =====

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 会话管理
    conv_id = req.conversation_id
    if conv_id:
        conv = conv_store.get(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conv = conv_store.get_or_create_active()
        conv_id = conv["id"]

    # 保存用户消息
    conv_store.add_message(conv_id, "user", req.question)

    def generate():
        full_text = ""
        sources = []

        for msg_type, data in get_engine().stream_query(req.question):
            if msg_type == "sources":
                sources = data
                yield f"data: {json.dumps({'type': 'sources', 'data': data})}\n\n"
            elif msg_type == "token":
                full_text += data
                yield f"data: {json.dumps({'type': 'token', 'data': data})}\n\n"
            elif msg_type == "error":
                yield f"data: {json.dumps({'type': 'error', 'data': data})}\n\n"
                return

        # 保存完整回答
        if full_text:
            conv_store.add_message(conv_id, "assistant", full_text, sources)

        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ===== 会话管理 =====

@app.post("/api/conversations")
async def create_conversation():
    conv = conv_store.create()
    return conv


@app.get("/api/conversations")
async def list_conversations():
    return conv_store.list_all()


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = conv_store.get(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    success = conv_store.delete(conv_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "deleted"}


@app.get("/api/conversations/active/latest")
async def get_active_conversation():
    conv = conv_store.get_or_create_active()
    return conv


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
