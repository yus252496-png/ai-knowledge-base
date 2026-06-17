import os
import json
import asyncio
import httpx
from typing import List
from pypdf import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, CHROMA_DIR, UPLOAD_DIR, USER_DATA_DIR
from database import get_db
from datetime import datetime


class _LocalEmbeddings(Embeddings):
    """直接包装 fastembed.TextEmbedding，绕过 langchain 的 FastEmbedEmbeddings 封装。"""
    def __init__(self, model_name: str = None):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model_name or "BAAI/bge-small-en-v1.5")

    def embed_query(self, text: str):
        return list(self._model.embed(text))[0]

    def embed_documents(self, texts: List[str]):
        return list(self._model.embed(texts))


class RAGEngine:
    def __init__(self, user_id: str = None):
        self._embeddings = None
        self.user_id = user_id
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
            self._embeddings = _LocalEmbeddings(model_name=EMBEDDING_MODEL)
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
                print(f"FAISS 加载失败({e})，将重建索引")
        # 本地无 FAISS 索引时，尝试从 PG 恢复 PDF 并重建
        if self.user_id and self._try_restore_from_pg():
            self._rebuild_index()
            self._persist()
            if os.path.exists(index_path):
                try:
                    return FAISS.load_local(
                        self.chroma_dir, self._get_embeddings(),
                        allow_dangerous_deserialization=True,
                    )
                except Exception as e:
                    print(f"FAISS 恢复后仍加载失败：{e}")
        dummy = Document(page_content="init", metadata={"source": "_init_"})
        try:
            store = FAISS.from_documents([dummy], self._get_embeddings())
            store.save_local(self.chroma_dir)
            return store
        except Exception as e:
            raise RuntimeError(f"向量引擎初始化失败，请检查嵌入模型配置：{e}")

    def _try_restore_from_pg(self) -> bool:
        """从 PostgreSQL 恢复 PDF 文件到本地。返回是否恢复了文档。"""
        try:
            with get_db() as db:
                rows = db.execute(
                    "SELECT doc_id, file_name, pdf_data FROM documents WHERE user_id = ? AND pdf_data IS NOT NULL",
                    (self.user_id,),
                ).fetchall()
            if not rows:
                return False
            os.makedirs(self.upload_dir, exist_ok=True)
            os.makedirs(self.chroma_dir, exist_ok=True)
            count = 0
            for r in rows:
                pdf_bytes = r["pdf_data"]
                if isinstance(pdf_bytes, memoryview):
                    pdf_bytes = bytes(pdf_bytes)
                if pdf_bytes:
                    file_path = os.path.join(self.upload_dir, f"{r['doc_id']}.pdf")
                    with open(file_path, "wb") as f:
                        f.write(pdf_bytes)
                    count += 1
            if count:
                print(f"已从 PG 恢复 {count} 个 PDF")
                # 同步元数据到本地
                self._pg_load_documents()
            return count > 0
        except Exception as e:
            print(f"从 PG 恢复 PDF 失败：{e}")
            return False

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
        # 同步到 PostgreSQL，确保重启后不丢失
        self._pg_save_metadata(metadata)

    def _pg_save_metadata(self, metadata: dict):
        """将文档元数据持久化到 PostgreSQL（不覆盖已有 pdf_data）"""
        if not self.user_id:
            return
        try:
            now = datetime.utcnow().isoformat()
            with get_db() as db:
                for doc_id, info in metadata.get("documents", {}).items():
                    db.execute(
                        "INSERT INTO documents (doc_id, user_id, file_name, total_pages, total_chunks, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (doc_id, user_id) DO UPDATE SET "
                        "file_name = EXCLUDED.file_name, "
                        "total_pages = EXCLUDED.total_pages, "
                        "total_chunks = EXCLUDED.total_chunks",
                        (doc_id, self.user_id, info.get("file_name", ""),
                         info.get("total_pages", 0), info.get("total_chunks", 0), now),
                    )
        except Exception as e:
            print(f"PG 元数据同步失败：{e}")

    def _pg_delete_document(self, doc_id: str):
        """从 PostgreSQL 删除文档"""
        if not self.user_id:
            return
        try:
            with get_db() as db:
                db.execute("DELETE FROM documents WHERE doc_id = ? AND user_id = ?", (doc_id, self.user_id))
        except Exception as e:
            print(f"PG 文档删除失败：{e}")

    def _pg_clear_documents(self):
        """清空 PostgreSQL 中的文档"""
        if not self.user_id:
            return
        try:
            with get_db() as db:
                db.execute("DELETE FROM documents WHERE user_id = ?", (self.user_id,))
        except Exception as e:
            print(f"PG 文档清空失败：{e}")

    def _pg_save_pdf(self, doc_id: str, pdf_bytes: bytes):
        """将 PDF 二进制内容存入 PostgreSQL"""
        if not self.user_id:
            return
        try:
            with get_db() as db:
                db.execute(
                    "UPDATE documents SET pdf_data = ? WHERE doc_id = ? AND user_id = ?",
                    (pdf_bytes, doc_id, self.user_id),
                )
        except Exception as e:
            print(f"PG PDF 存储失败：{e}")

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

    def process_pdf(self, file_path: str, doc_id: str, original_name: str = None, pdf_bytes: bytes = None) -> dict:
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
        try:
            for i in range(0, len(chunks), batch_size):
                store.add_documents(chunks[i:i + batch_size])
            self._persist()
        except Exception as e:
            # 失败时重置 store，下次访问从磁盘重新加载
            self._store = None
            raise RuntimeError(f"向量索引写入失败：{e}")

        meta = self._load_metadata()
        meta["documents"][doc_id] = {
            "file_name": display_name,
            "total_pages": len(pages),
            "total_chunks": len(chunks),
        }
        self._save_metadata(meta)

        # 将 PDF 二进制存入 PostgreSQL
        if pdf_bytes:
            self._pg_save_pdf(doc_id, pdf_bytes)

        return {
            "doc_id": doc_id,
            "file_name": display_name,
            "total_pages": len(pages),
            "total_chunks": len(chunks),
        }

    def query(self, question: str, k: int = 5, doc_ids: list = None) -> dict:
        result = self.retrieve(question, k, doc_ids=doc_ids)
        if result.get("error"):
            return {"answer": result["error"], "sources": []}
        if not result.get("context"):
            return result

        system_prompt = "你是一个基于知识库的问答助手。请根据提供的上下文来回答问题。你可以基于上下文进行总结、推理和分析，必要时用自己的知识补充说明。如果上下文中完全没有相关信息，明确告诉用户找不到相关信息。用中文回答。"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"上下文信息：\n{result['context']}\n\n问题：{question}"},
        ]

        try:
            resp = httpx.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": messages,
                    "stream": False,
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            return {"answer": answer, "sources": result["sources"]}
        except Exception as e:
            return {"answer": f"大模型调用失败：{e}", "sources": result["sources"]}

    def retrieve(self, question: str, k: int = 5, doc_ids: list = None) -> dict:
        try:
            store = self._get_store()

            # 文档过滤：doc_ids 非空时只搜索指定文档
            filter_fn = None
            effective_k = k
            if doc_ids is not None and len(doc_ids) > 0:
                doc_ids_set = set(doc_ids)
                filter_fn = lambda md: md.get("doc_id") in doc_ids_set
                effective_k = k * 3  # FAISS 是后过滤，放大 k 保证结果数

            try:
                docs_with_scores = store.similarity_search_with_score(question, k=effective_k, filter=filter_fn)
            except Exception:
                # 带 filter 查询失败时（如 FAISS 索引只有占位文档），降级为无过滤查询
                docs_with_scores = store.similarity_search_with_score(question, k=k)
        except Exception:
            return {"error": "知识库为空，请先上传文档。", "sources": [], "context": ""}

        relevant_docs = [(doc, score) for doc, score in docs_with_scores
                         if doc.metadata.get("source") != "_init_"]

        if not relevant_docs and self.user_id:
            # 可能是容器重启后 FAISS 索引未重建，尝试从 PG 恢复
            if self._try_restore_from_pg():
                self._rebuild_index()
                self._persist()
                self._store = None  # 下次重新加载
                try:
                    store = self._get_store()
                    docs_with_scores = store.similarity_search_with_score(question, k=effective_k, filter=filter_fn)
                    relevant_docs = [(doc, score) for doc, score in docs_with_scores
                                     if doc.metadata.get("source") != "_init_"]
                except Exception:
                    pass

        if doc_ids and not relevant_docs:
            # 用户选了文档但没有匹配结果，可能是索引与元数据不同步，强制重建
            if self._try_restore_from_pg():
                self._rebuild_index()
                self._persist()
                self._store = None
                try:
                    store = self._get_store()
                    docs_with_scores = store.similarity_search_with_score(question, k=effective_k, filter=filter_fn)
                    relevant_docs = [(doc, score) for doc, score in docs_with_scores
                                     if doc.metadata.get("source") != "_init_"]
                except Exception:
                    pass

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

    def stream_query(self, question: str, k: int = 5, doc_ids: list = None):
        result = self.retrieve(question, k, doc_ids=doc_ids)
        if result.get("error"):
            yield ("error", result["error"])
            return
        if not result.get("context"):
            yield ("error", "未在已上传的文档中找到相关信息")
            return

        yield ("sources", result["sources"])

        system_prompt = "你是一个基于知识库的问答助手。请根据提供的上下文来回答问题。你可以基于上下文进行总结、推理和分析，必要时用自己的知识补充说明。如果上下文中完全没有相关信息，明确告诉用户找不到相关信息。用中文回答。"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"上下文信息：\n{result['context']}\n\n问题：{question}"},
        ]

        try:
            with httpx.Client(timeout=30) as client:
                with client.stream(
                    "POST",
                    f"{LLM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": LLM_MODEL,
                        "messages": messages,
                        "stream": True,
                        "temperature": 0.3,
                        "max_tokens": 4096,
                    },
                ) as resp:
                    if resp.status_code != 200:
                        yield ("error", f"LLM API error: {resp.status_code}")
                        return
                    for line in resp.iter_lines():
                        if line.startswith("data: "):
                            payload = line[6:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield ("token", content)
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            yield ("error", f"大模型调用失败：{e}")

    async def astream_query(self, question: str, k: int = 5, doc_ids: list = None):
        import time as _time
        _t0 = _time.time()
        print(f"[astream] retrieve start at t={_time.time()-_t0:.1f}s")
        # retrieve() 是同步操作，在线程池中运行避免阻塞事件循环
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.retrieve, question, k, doc_ids)
        print(f"[astream] retrieve done at t={_time.time()-_t0:.1f}s")
        if result.get("error"):
            print(f"[astream] retrieve error: {result['error']}")
            yield ("error", result["error"])
            return
        if not result.get("context"):
            print(f"[astream] no context found")
            yield ("error", "未在已上传的文档中找到相关信息")
            return

        print(f"[astream] yielding sources at t={_time.time()-_t0:.1f}s")
        yield ("sources", result["sources"])
        print(f"[astream] sources yielded, starting LLM at t={_time.time()-_t0:.1f}s")

        system_prompt = "你是一个基于知识库的问答助手。请根据提供的上下文来回答问题。你可以基于上下文进行总结、推理和分析，必要时用自己的知识补充说明。如果上下文中完全没有相关信息，明确告诉用户找不到相关信息。用中文回答。"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"上下文信息：\n{result['context']}\n\n问题：{question}"},
        ]

        try:
            print(f"[astream] httpx astream start at t={_time.time()-_t0:.1f}s")
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                async with client.stream(
                    "POST",
                    f"{LLM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": LLM_MODEL,
                        "messages": messages,
                        "stream": True,
                        "temperature": 0.3,
                        "max_tokens": 4096,
                    },
                ) as resp:
                    if resp.status_code != 200:
                        err_msg = f"LLM API error: HTTP {resp.status_code}"
                        print(f"[astream] {err_msg}")
                        yield ("error", err_msg)
                        return
                    token_count = 0
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            payload = line[6:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    token_count += 1
                                    yield ("token", content)
                            except json.JSONDecodeError:
                                pass
                    print(f"[astream] LLM done at t={_time.time()-_t0:.1f}s, {token_count} tokens")
        except httpx.TimeoutException:
            print(f"[astream] LLM timeout at t={_time.time()-_t0:.1f}s")
            yield ("error", "大模型响应超时，请稍后重试")
        except Exception as e:
            print(f"[astream] LLM error at t={_time.time()-_t0:.1f}s: {e}")
            yield ("error", f"大模型调用失败：{e}")

    def list_documents(self) -> List[dict]:
        meta = self._load_metadata()
        docs = meta.get("documents", {})
        if not docs and self.user_id:
            # metadata.json 为空时尝试从 PostgreSQL 恢复
            docs = self._pg_load_documents()
        return [
            {
                "doc_id": doc_id,
                "file_name": info.get("file_name", doc_id),
                "total_pages": info.get("total_pages", 0),
                "total_chunks": info.get("total_chunks", 0),
            }
            for doc_id, info in docs.items()
        ]

    def _pg_load_documents(self) -> dict:
        """从 PostgreSQL 加载文档元数据"""
        if not self.user_id:
            return {}
        try:
            with get_db() as db:
                rows = db.execute(
                    "SELECT doc_id, file_name, total_pages, total_chunks FROM documents WHERE user_id = ?",
                    (self.user_id,),
                ).fetchall()
            result = {}
            for r in rows:
                result[r["doc_id"]] = {
                    "file_name": r["file_name"],
                    "total_pages": r["total_pages"],
                    "total_chunks": r["total_chunks"],
                }
            if result:
                # 同步回文件系统
                meta = self._load_metadata()
                meta["documents"] = result
                self._save_metadata(meta)
            return result
        except Exception as e:
            print(f"PG 文档加载失败：{e}")
            return {}

    def _remove_index_files(self):
        """删除 FAISS 索引文件，触发下次查询时自动重建"""
        import glob as _glob
        for f in _glob.glob(os.path.join(self.chroma_dir, "index.faiss*")):
            try:
                os.remove(f)
            except OSError:
                pass
        for f in _glob.glob(os.path.join(self.chroma_dir, "index.pkl")):
            try:
                os.remove(f)
            except OSError:
                pass

    def delete_document(self, doc_id: str) -> bool:
        meta = self._load_metadata()
        if doc_id not in meta.get("documents", {}):
            return False
        del meta["documents"][doc_id]
        self._save_metadata(meta)
        self._pg_delete_document(doc_id)
        # 删除本地 PDF 文件
        file_path = os.path.join(self.upload_dir, f"{doc_id}.pdf")
        if os.path.exists(file_path):
            os.remove(file_path)
        # 清空 store 缓存并删除索引文件，下次查询时自动重建
        self._store = None
        self._remove_index_files()
        return True

    def clear_documents(self):
        meta = self._load_metadata()
        meta["documents"] = {}
        self._save_metadata(meta)
        self._pg_clear_documents()
        # 清空 store 缓存并删除索引文件，下次查询时自动重建
        self._store = None
        self._remove_index_files()

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
