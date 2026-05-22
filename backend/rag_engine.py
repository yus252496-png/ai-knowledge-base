import os
import json
from typing import List
from pypdf import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_openai import ChatOpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, CHROMA_DIR, UPLOAD_DIR, USER_DATA_DIR


class RAGEngine:
    def __init__(self, user_id: str = None):
        self._embeddings = None
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        )

        if user_id:
            user_dir = os.path.join(USER_DATA_DIR, user_id)
            self.upload_dir = os.path.join(user_dir, "uploads")
            self.chroma_dir = os.path.join(user_dir, "chroma_db")
        else:
            self.upload_dir = UPLOAD_DIR
            self.chroma_dir = CHROMA_DIR

        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.chroma_dir, exist_ok=True)

        self.meta_path = os.path.join(self.chroma_dir, "metadata.json")
        self._store = None  # 延迟初始化

    def _get_embeddings(self):
        if self._embeddings is None:
            if not LLM_API_KEY:
                raise RuntimeError(
                    "LLM_API_KEY 未配置，请在环境变量中设置。"
                )
            self._embeddings = FastEmbedEmbeddings(model_name=EMBEDDING_MODEL)
        return self._embeddings

    def _get_store(self):
        if self._store is None:
            self._store = self._load_or_create_store()
        return self._store

    def _load_or_create_store(self):
        index_path = os.path.join(self.chroma_dir, "index.faiss")
        if os.path.exists(index_path):
            try:
                return FAISS.load_local(
                    self.chroma_dir, self._get_embeddings(),
                    allow_dangerous_deserialization=True,
                )
            except Exception as e:
                print(f"FAISS 加载失败，将重建索引：{e}")
        dummy = Document(page_content="init", metadata={"source": "_init_"})
        try:
            store = FAISS.from_documents([dummy], self._get_embeddings())
            store.save_local(self.chroma_dir)
            return store
        except Exception as e:
            raise RuntimeError(f"向量引擎初始化失败，请检查 API 密钥和账户余额：{e}")

    def _persist(self):
        try:
            self._get_store().save_local(self.chroma_dir)
        except Exception as e:
            print(f"FAISS 持久化失败：{e}")

    def _load_metadata(self) -> dict:
        if os.path.exists(self.meta_path):
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"documents": {}}

    def _save_metadata(self, metadata: dict):
        os.makedirs(self.chroma_dir, exist_ok=True)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def _extract_pdf_text(self, file_path: str) -> list:
        reader = PdfReader(file_path)
        documents = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text.strip():
                documents.append(Document(
                    page_content=text.strip(),
                    metadata={"page": i, "source": os.path.basename(file_path)},
                ))
        return documents

    def _build_llm(self, **kwargs):
        return ChatOpenAI(
            model=LLM_MODEL,
            openai_api_key=LLM_API_KEY,
            openai_api_base=LLM_BASE_URL,
            temperature=0.3,
            **kwargs,
        )

    def process_pdf(self, file_path: str, doc_id: str, original_name: str = None) -> dict:
        pages = self._extract_pdf_text(file_path)
        if not pages:
            raise ValueError("未能从 PDF 中提取到文本内容")

        display_name = original_name or os.path.basename(file_path)

        chunks = self.text_splitter.split_documents(pages)

        for i, chunk in enumerate(chunks):
            chunk.metadata["doc_id"] = doc_id
            chunk.metadata["chunk_id"] = f"{doc_id}_{i}"
            chunk.metadata["source"] = display_name

        store = self._get_store()
        batch_size = 10
        for i in range(0, len(chunks), batch_size):
            store.add_documents(chunks[i:i + batch_size])
        self._persist()

        meta = self._load_metadata()
        meta["documents"][doc_id] = {
            "file_name": display_name,
            "total_pages": len(pages),
            "total_chunks": len(chunks),
        }
        self._save_metadata(meta)

        return {
            "doc_id": doc_id,
            "file_name": display_name,
            "total_pages": len(pages),
            "total_chunks": len(chunks),
        }

    def query(self, question: str, k: int = 5) -> dict:
        result = self.retrieve(question, k)
        if result.get("error"):
            return {"answer": result["error"], "sources": []}
        if not result.get("context"):
            return result

        system_prompt = "你是一个基于知识库的问答助手。请根据提供的上下文回答问题。如果上下文中没有足够信息，明确告诉用户找不到相关信息。用中文回答。不要添加上下文之外的信息。"
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"上下文信息：\n{result['context']}\n\n问题：{question}"),
        ]

        llm = self._build_llm()
        try:
            response = llm.invoke(messages)
            return {"answer": response.content, "sources": result["sources"]}
        except Exception as e:
            return {"answer": f"大模型调用失败：{e}", "sources": result["sources"]}

    def retrieve(self, question: str, k: int = 5) -> dict:
        try:
            store = self._get_store()
            docs_with_scores = store.similarity_search_with_score(question, k=k)
        except Exception:
            return {"error": "知识库为空，请先上传文档。", "sources": [], "context": ""}

        relevant_docs = [(doc, score) for doc, score in docs_with_scores
                         if doc.metadata.get("source") != "_init_"]

        if not relevant_docs:
            return {
                "answer": "未在已上传的文档中找到相关信息，请尝试换个问题或上传相关文档。",
                "sources": [], "context": "",
            }

        context_parts, seen_sources, sources = [], set(), []
        for doc, score in relevant_docs:
            context_parts.append(doc.page_content)
            src_key = doc.metadata.get("source", "未知来源")
            if src_key not in seen_sources:
                seen_sources.add(src_key)
                sources.append({
                    "file_name": src_key,
                    "page": doc.metadata.get("page", 0) + 1,
                    "score": round(float(score), 4),
                    "content": doc.page_content[:200] + ("..." if len(doc.page_content) > 200 else ""),
                })

        return {"context": "\n---\n".join(context_parts), "sources": sources}

    def stream_query(self, question: str, k: int = 5):
        result = self.retrieve(question, k)
        if result.get("error"):
            yield ("error", result["error"])
            return
        if not result.get("context"):
            yield ("error", "未在已上传的文档中找到相关信息")
            return

        yield ("sources", result["sources"])

        system_prompt = "你是一个基于知识库的问答助手。请根据提供的上下文回答问题。如果上下文中没有足够信息，明确告诉用户找不到相关信息。用中文回答。不要添加上下文之外的信息。"
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"上下文信息：\n{result['context']}\n\n问题：{question}"),
        ]

        llm = self._build_llm()
        try:
            for chunk in llm.stream(messages):
                if chunk.content:
                    yield ("token", chunk.content)
        except Exception as e:
            yield ("error", f"大模型调用失败：{e}")

    def list_documents(self) -> List[dict]:
        meta = self._load_metadata()
        return [
            {
                "doc_id": doc_id,
                "file_name": info.get("file_name", doc_id),
                "total_pages": info.get("total_pages", 0),
                "total_chunks": info.get("total_chunks", 0),
            }
            for doc_id, info in meta.get("documents", {}).items()
        ]

    def delete_document(self, doc_id: str) -> bool:
        meta = self._load_metadata()
        if doc_id not in meta.get("documents", {}):
            return False
        del meta["documents"][doc_id]
        self._save_metadata(meta)
        self._rebuild_index()
        self._persist()
        return True

    def clear_documents(self):
        meta = self._load_metadata()
        meta["documents"] = {}
        self._save_metadata(meta)
        self._rebuild_index()
        self._persist()

    def _rebuild_index(self):
        meta = self._load_metadata()
        dummy = Document(page_content="init", metadata={"source": "_init_"})
        try:
            self._store = FAISS.from_documents([dummy], self._get_embeddings())
        except Exception as e:
            raise RuntimeError(f"向量引擎重建失败：{e}")

        store = self._store

        batch_size = 10
        for doc_id, info in meta.get("documents", {}).items():
            file_name = info.get("file_name", "")
            storage_name = f"{doc_id}.pdf"
            file_path = os.path.join(self.upload_dir, storage_name)
            if os.path.exists(file_path):
                pages = self._extract_pdf_text(file_path)
                if pages:
                    chunks = self.text_splitter.split_documents(pages)
                    for i, chunk in enumerate(chunks):
                        chunk.metadata["doc_id"] = doc_id
                        chunk.metadata["chunk_id"] = f"{doc_id}_{i}"
                        chunk.metadata["source"] = file_name
                    for i in range(0, len(chunks), batch_size):
                        store.add_documents(chunks[i:i + batch_size])
