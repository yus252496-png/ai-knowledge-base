import os
import json
from typing import List
from pypdf import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_dashscope import DashScopeEmbeddings
import dashscope
from config import DASHSCOPE_API_KEY, LLM_MODEL, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, CHROMA_DIR, UPLOAD_DIR, USER_DATA_DIR


dashscope.api_key = DASHSCOPE_API_KEY


class RAGEngine:
    def __init__(self, user_id: str = None):
        self.embeddings = DashScopeEmbeddings(
            model=EMBEDDING_MODEL,
            dashscope_api_key=DASHSCOPE_API_KEY,
        )
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
        self.vector_store = self._load_or_create_store()

    def _load_or_create_store(self):
        index_path = os.path.join(self.chroma_dir, "index.faiss")
        if os.path.exists(index_path):
            try:
                return FAISS.load_local(
                    self.chroma_dir, self.embeddings,
                    allow_dangerous_deserialization=True,
                )
            except Exception as e:
                print(f"FAISS 加载失败，将重建索引：{e}")
        dummy = Document(page_content="init", metadata={"source": "_init_"})
        store = FAISS.from_documents([dummy], self.embeddings)
        store.save_local(self.chroma_dir)
        return store

    def _persist(self):
        try:
            self.vector_store.save_local(self.chroma_dir)
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

        batch_size = 10
        for i in range(0, len(chunks), batch_size):
            self.vector_store.add_documents(chunks[i:i + batch_size])
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
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"上下文信息：\n{result['context']}\n\n问题：{question}"},
        ]

        response = dashscope.Generation.call(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.3,
            result_format="message",
        )

        if response.status_code != 200:
            return {"answer": f"大模型调用失败：{response.message}", "sources": result["sources"]}

        return {"answer": response.output.choices[0].message.content, "sources": result["sources"]}

    def retrieve(self, question: str, k: int = 5) -> dict:
        try:
            docs_with_scores = self.vector_store.similarity_search_with_score(question, k=k)
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
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"上下文信息：\n{result['context']}\n\n问题：{question}"},
        ]

        responses = dashscope.Generation.call(
            model=LLM_MODEL,
            messages=messages,
            stream=True,
            temperature=0.3,
            result_format="message",
        )

        for chunk in responses:
            if chunk.status_code == 200:
                token = chunk.output.choices[0].message.content
                if token:
                    yield ("token", token)

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
        self.vector_store = FAISS.from_documents([dummy], self.embeddings)

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
                        self.vector_store.add_documents(chunks[i:i + batch_size])
