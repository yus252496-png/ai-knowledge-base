# AI 知识库 — CLAUDE.md

## 项目概况

RAG（检索增强生成）知识库问答系统。

- **前端**：Vue 3 (Composition API, `<script setup>`) + Vite，部署在 Vercel
- **后端**：FastAPI + uvicorn，部署在 Railway
- **数据库**：PostgreSQL（生产）/ SQLite（本地开发）
- **向量引擎**：FAISS + BAAI/bge-small-en-v1.5 嵌入模型
- **LLM**：DeepSeek API（通过 langchain-openai 调用）
- **认证**：JWT + 图片验证码 + 双角色（user/admin）
- **自定义域名**：`https://www.elaik.cn`

## 项目结构

```
ai-knowledge-base/
├── backend/
│   ├── main.py            # FastAPI 应用入口，路由定义
│   ├── rag_engine.py      # RAG 引擎：文档处理、向量检索、LLM 调用
│   ├── auth.py            # 认证：JWT、验证码、用户管理、登录限流
│   ├── config.py          # 配置项（环境变量读取）
│   ├── conversations.py   # 会话管理
│   ├── database.py        # 数据库抽象层（SQLite / PostgreSQL 统一接口）
│   ├── restart.sh         # 本地安全重启脚本
│   └── start.sh           # Railway 部署启动脚本
├── frontend/
│   ├── src/
│   │   ├── api/index.js           # API 客户端（Axios + Fetch SSE）
│   │   ├── views/
│   │   │   ├── ChatView.vue       # 主聊天页（文档管理 + 对话）
│   │   │   ├── LoginView.vue      # 登录
│   │   │   ├── RegisterView.vue   # 注册
│   │   │   ├── ForgotPasswordView.vue  # 忘记密码
│   │   │   └── AdminView.vue      # 后台管理
│   │   └── ...
│   └── vite.config.js
├── Procfile               # Railway 部署配置
└── CLAUDE.md
```

## 开发准则

### 1. 先想后写

- 不确定的实现方案先问清楚再动手
- 如果同一个需求有多个合理实现方式，列出选择
- 觉得某个需求有问题或可以更简单，直接指出来

### 2. 保持简单

- 只做被要求的，不做"以后可能会用到"的
- 不要为单次使用场景造通用抽象/工具函数
- 不要加多余的可配置性、灵活性

### 3. 手术刀式修改

- 只动和需求直接相关的代码
- 不改动相邻代码的注释、格式、样式
- 不要顺手重构没坏的东西
- 匹配既有代码风格

当你的改动产生垃圾时：
- 删掉因你改动而不再使用的变量/import/函数
- 不要顺手删已有的废弃代码，除非被问及

### 4. 目标驱动

复杂任务先列步骤再动手：
```
1. [做什么] → 验证方式：[怎么确认做对了]
2. [做什么] → 验证方式：[怎么确认做对了]
```

### 分支策略

- `main` — 唯一分支，直接在上面开发和提交
- 改完后推送到远程

## 后端关键信息

### RAG 引擎 (rag_engine.py)

- `RAGEngine` 按 `user_id` 实例化，每个用户独立目录
- 文档处理流程：pypdf 提取 → RecursiveCharacterTextSplitter 分块 → fastembed 向量化 → FAISS 索引
- 分块参数：`CHUNK_SIZE=500`, `CHUNK_OVERLAP=100`
- LLM 流式调用每 chunk 有 10s 超时，总超时 15s
- 删除文档时不重建索引，改为懒加载（下次查询时自动重建）

### API 端点 (main.py)

| 端点 | 说明 |
|------|------|
| `POST /api/auth/register` | 注册 |
| `POST /api/auth/login` | 登录（含验证码） |
| `GET /api/auth/captcha` | 图片验证码 |
| `POST /api/chat/stream` | 流式对话（SSE） |
| `POST /api/chat` | 非流式对话 |
| `POST /api/upload` | 上传 PDF |
| `GET /api/documents` | 文档列表 |
| `DELETE /api/documents/{id}` | 删除文档 |
| `GET /api/conversations` | 会话列表 |

### SSE 流式响应

- 使用 `text/plain` 而非 `text/event-stream`（避免 Railway 代理缓冲）
- 事件格式：`data: {"type": "connected|sources|token|error|done", "data": ...}\n\n`
- 启动时 `connected` 事件确保连接立即建立
- 客户端通过 `AbortController` 中断流式响应
- 同步操作（如 FAISS 检索）在线程池中运行，不阻塞事件循环

### 启动预热

启动时自动执行：
1. 数据库初始化
2. 嵌入模型预下载（避免首次请求触发下载）
3. LLM API 连通性检测

## 前端关键信息

- 使用 Vue 3 Composition API（`ref`、`computed`、`watch`）
- 流式对话通过 `fetch` + `response.body.getReader()` 实现
- 打字机效果：`setInterval` 逐字从完整文本中取出字符
- API 基础地址由 `VITE_API_URL` 环境变量控制，空字符串即同源代理
- 文档选择器：`selectedDocIds` 数组，支持多选，删除文档时自动清理失效 ID

## 部署

- **前端**：Vercel，`vercel --prod` 部署
- **后端**：Railway，git push 到 main 自动部署
- Railway 环境变量需设置：`LLM_API_KEY`、`DATABASE_URL`、`JWT_SECRET`
- Railway 可选设置：`FRONTEND_URL`（CORS 白名单）、`LLM_MODEL`、`LLM_BASE_URL`
