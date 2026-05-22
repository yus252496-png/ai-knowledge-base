<template>
  <div class="app-container">
    <!-- 侧栏（移动端：遮罩 + 抽屉） -->
    <div v-if="showSidebar" class="sidebar-backdrop" @click="showSidebar = false"></div>
    <aside class="sidebar" :class="{ 'sidebar--open': showSidebar }">
      <!-- 会话列表 -->
      <div class="section">
        <div class="section-header">
          <span>对话历史</span>
          <button class="btn-new" @click="newConversation" title="新对话">+</button>
        </div>
        <div class="conv-list">
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="conv-item"
            :class="{ active: conv.id === currentConvId }"
            @click="switchConversation(conv.id)"
          >
            <span class="conv-title">{{ conv.title }}</span>
            <span class="conv-meta">{{ conv.message_count }} 条</span>
            <button class="btn-del" @click.stop="removeConversation(conv.id)" title="删除">✕</button>
          </div>
          <div v-if="conversations.length === 0" class="empty-hint">暂无对话记录</div>
        </div>
      </div>
      <!-- 文档管理 -->
      <div class="section">
        <div class="section-header">
          <span>文档管理</span>
        </div>
        <div class="upload-area">
          <label class="upload-btn" :class="{ uploading }" :style="uploadBtnStyle">
            {{ uploading ? `上传中 ${uploadProgress}%` : '上传 PDF' }}
            <input type="file" accept=".pdf" multiple @change="handleUpload" :disabled="uploading" />
          </label>
        </div>
        <div class="doc-list">
          <div v-if="documents.length === 0" class="empty-hint">暂无文档</div>
          <div v-for="doc in documents" :key="doc.doc_id" class="doc-item">
            <div class="doc-info">
              <span class="doc-name">{{ doc.file_name }}</span>
              <span class="doc-meta">{{ doc.total_chunks }} 段</span>
            </div>
            <button class="btn-del" @click="removeDoc(doc.doc_id)" title="删除">✕</button>
          </div>
        </div>
      </div>
      <!-- 用户信息 -->
      <div class="user-section">
        <span class="user-phone">{{ phone }}</span>
        <div class="user-actions">
          <button v-if="isAdmin" class="btn-admin" @click="goAdmin">后台管理</button>
          <button class="btn-logout" @click="handleLogout">退出</button>
        </div>
      </div>
    </aside>

    <!-- 主区域 -->
    <main class="main-area">
      <div class="chat-header">
        <div class="chat-header-left">
          <button class="btn-menu" @click="showSidebar = !showSidebar" title="菜单">☰</button>
          <h1>{{ currentTitle }}</h1>
        </div>
        <span class="doc-count">{{ documents.length }} 个文档</span>
      </div>
      <div class="messages" ref="messagesRef">
        <div v-if="messages.length === 0" class="welcome">
          <div class="welcome-icon">☁</div>
          <p>上传 PDF 文档后开始提问</p>
        </div>
        <div v-for="(msg, idx) in messages" :key="idx" class="message" :class="msg.role">
          <div class="msg-content">{{ msg.content }}</div>
          <div v-if="msg.sources && msg.sources.length" class="sources">
            <div class="source-title">来源</div>
            <div v-for="(src, si) in msg.sources" :key="si" class="source-item">
              {{ src.file_name }} 第{{ src.page }}页
            </div>
          </div>
        </div>
        <div v-if="(loading || streamingMsg.content) && streamingMsg.content !== undefined" class="message assistant">
          <div class="msg-content">{{ streamingMsg.display }}<span v-if="streamingMsg.display.length < streamingMsg.content.length" class="cursor">|</span></div>
          <div v-if="streamingMsg.sources && streamingMsg.sources.length" class="sources">
            <div class="source-title">来源</div>
            <div v-for="(src, si) in streamingMsg.sources" :key="si" class="source-item">
              {{ src.file_name }} 第{{ src.page }}页
            </div>
          </div>
        </div>
      </div>
      <div class="input-area">
        <input
          v-model="question"
          type="text"
          placeholder="输入问题..."
          @keydown.enter="sendMessage"
          :disabled="loading"
        />
        <button @click="sendMessage" :disabled="!question.trim() || loading">发送</button>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  uploadDocument, chat, chatStream, listDocuments, deleteDocument, clearDocuments,
  listConversations, createConversation, getConversation, deleteConversation, getActiveConversation,
} from '../api/index.js'
import { authState } from '../stores/auth.js'
import { getCurrentUser } from '../api/index.js'

const router = useRouter()

const documents = ref([])
const conversations = ref([])
const messages = ref([])
const currentConvId = ref(null)
const question = ref('')
const loading = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const messagesRef = ref(null)
const showSidebar = ref(false)

const phone = computed(() => authState.phone.value)
const isAdmin = computed(() => authState.isAdmin.value)

function goAdmin() {
  router.push('/admin')
}

// 流式输出状态
const streamingMsg = ref({ content: '', sources: [], display: '' })
let typewriterTimer = null

const currentTitle = computed(() => {
  const conv = conversations.value.find(c => c.id === currentConvId.value)
  return conv ? conv.title : '知识库问答'
})

const uploadBtnStyle = computed(() => {
  if (!uploading.value || uploadProgress.value === 0) return {}
  return {
    background: `linear-gradient(to right, #dbeafe ${uploadProgress.value}%, #f5f5f5 ${uploadProgress.value}%)`,
    borderColor: uploadProgress.value === 100 ? '#22c55e' : '#93c5fd',
    color: uploadProgress.value > 50 ? '#1e40af' : '#888',
  }
})

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function handleLogout() {
  authState.logout()
  router.push('/login')
}

// ===== 会话管理 =====

async function loadConversations() {
  try {
    const res = await listConversations()
    conversations.value = res.data || []
  } catch (e) {
    console.error('加载对话列表失败', e)
  }
}

async function loadActiveConversation() {
  try {
    const res = await getActiveConversation()
    const conv = res.data
    currentConvId.value = conv.id
    messages.value = conv.messages || []
    await nextTick()
    scrollToBottom()
  } catch (e) {
    console.error('加载当前对话失败', e)
  }
}

async function newConversation() {
  showSidebar.value = false
  try {
    const res = await createConversation()
    currentConvId.value = res.data.id
    messages.value = []
    await loadConversations()
  } catch (e) {
    console.error('创建对话失败', e)
  }
}

async function switchConversation(convId) {
  if (convId === currentConvId.value) return
  showSidebar.value = false
  try {
    const res = await getConversation(convId)
    const conv = res.data
    currentConvId.value = conv.id
    messages.value = conv.messages || []
    await loadConversations()
    scrollToBottom()
  } catch (e) {
    console.error('切换对话失败', e)
  }
}

async function removeConversation(convId) {
  try {
    await deleteConversation(convId)
    if (convId === currentConvId.value) {
      currentConvId.value = null
      messages.value = []
      await loadActiveConversation()
    }
    await loadConversations()
  } catch (e) {
    console.error('删除对话失败', e)
  }
}

// ===== 文档管理 =====

async function loadDocuments() {
  try {
    const res = await listDocuments()
    documents.value = res.data || []
  } catch (e) {
    console.error('加载文档列表失败', e)
  }
}

const MAX_FILE_SIZE = 20 * 1024 * 1024 // 20MB

async function handleUpload(e) {
  const files = e.target.files
  if (!files.length) return

  // 前端文件大小检查
  for (const file of files) {
    if (file.size > MAX_FILE_SIZE) {
      alert(`「${file.name}」超过 20MB，请压缩后重新上传。`)
      e.target.value = ''
      return
    }
  }

  uploading.value = true
  for (const file of files) {
    uploadProgress.value = 0
    try {
      await uploadDocument(file, (pct) => { uploadProgress.value = pct })
    } catch (e) {
      console.error(`上传 ${file.name} 失败`, e)
    }
  }
  uploadProgress.value = 0
  uploading.value = false
  e.target.value = ''
  await loadDocuments()
}

async function removeDoc(docId) {
  try {
    await deleteDocument(docId)
    await loadDocuments()
  } catch (e) {
    console.error('删除失败', e)
  }
}

// ===== 聊天（流式 + 打字机） =====

function ensureTypewriter() {
  if (typewriterTimer) return

  typewriterTimer = setInterval(() => {
    const content = streamingMsg.value.content
    const display = streamingMsg.value.display

    if (content && display.length < content.length) {
      const newPos = display.length + 1
      streamingMsg.value = { ...streamingMsg.value, display: content.slice(0, newPos) }
      scrollToBottom()
    } else if (!loading.value) {
      clearInterval(typewriterTimer)
      typewriterTimer = null
      if (content) {
        messages.value.push({
          role: 'assistant',
          content,
          sources: streamingMsg.value.sources,
        })
      }
      streamingMsg.value = { content: '', sources: [], display: '' }
      scrollToBottom()
    }
  }, 40)
}

async function sendMessage() {
  const q = question.value.trim()
  if (!q || loading.value) return

  messages.value.push({ role: 'user', content: q })
  question.value = ''
  loading.value = true

  streamingMsg.value = { content: '', sources: [], display: '' }
  if (typewriterTimer) {
    clearInterval(typewriterTimer)
    typewriterTimer = null
  }
  scrollToBottom()

  let fullContent = ''
  let msgSources = []

  chatStream(q, currentConvId.value, {
    onMessage(msg) {
      if (msg.type === 'fulltext') {
        fullContent = msg.data
        streamingMsg.value = {
          ...streamingMsg.value,
          content: msg.data,
          display: streamingMsg.value.display || msg.data.slice(0, 1),
        }
        ensureTypewriter()
      } else if (msg.type === 'sources') {
        msgSources = msg.data
        streamingMsg.value = { ...streamingMsg.value, sources: msgSources }
      } else if (msg.type === 'done') {
        currentConvId.value = msg.conversation_id
      } else if (msg.type === 'error') {
        streamingMsg.value = { ...streamingMsg.value, content: msg.data, display: msg.data }
      }
    },
    onComplete() {
      loading.value = false
      loadConversations()
    },
    onError(err) {
      if (typewriterTimer) {
        clearInterval(typewriterTimer)
        typewriterTimer = null
      }
      streamingMsg.value = { content: '', sources: [], display: '' }
      messages.value.push({
        role: 'assistant',
        content: '请求失败，请检查后端服务是否正常运行。',
      })
      loading.value = false
      scrollToBottom()
    },
  })
}

async function loadMyRole() {
  try {
    const res = await getCurrentUser()
    if (res.data.role) authState.setRole(res.data.role)
  } catch {}
}

onMounted(async () => {
  await loadMyRole()
  await loadConversations()
  await loadActiveConversation()
  await loadDocuments()
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 13px;
  color: #1f1f1f;
}

.app-container {
  display: flex;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: #f7f7f8;
}

/* ===== 侧栏 ===== */
.sidebar {
  width: 260px;
  background: #fff;
  border-right: 1px solid #e8e8ea;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.section {
  display: flex;
  flex-direction: column;
}
.section + .section {
  border-top: 1px solid #e8e8ea;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 8px;
  font-size: 12px;
  font-weight: 600;
  color: #888;
  letter-spacing: 0.3px;
}

.btn-new {
  width: 22px; height: 22px;
  border: 1px solid #e0e0e0;
  background: #fff;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  color: #888;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.btn-new:hover { border-color: #1f1f1f; color: #1f1f1f; }

.conv-list, .doc-list {
  overflow-y: auto;
  padding: 0 8px 8px;
}
.conv-list { max-height: 35vh; }

.conv-item, .doc-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 7px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s;
}
.conv-item:hover, .doc-item:hover { background: #f5f5f5; }
.conv-item.active { background: #f0f0f0; }

.conv-title, .doc-name {
  flex: 1;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1f1f1f;
}
.conv-meta, .doc-meta {
  font-size: 10px;
  color: #bbb;
  flex-shrink: 0;
}
.btn-del {
  background: none; border: none; color: #d0d0d0; cursor: pointer;
  font-size: 10px; padding: 2px 4px; border-radius: 4px; flex-shrink: 0;
  opacity: 0; transition: all 0.15s;
}
.conv-item:hover .btn-del, .doc-item:hover .btn-del { opacity: 1; }
.btn-del:hover { color: #e03e3e; background: #fef2f2; }

.empty-hint { text-align: center; color: #ccc; padding: 20px 0; font-size: 12px; }

.upload-area { padding: 6px 8px 8px; }
.upload-btn {
  display: block;
  padding: 7px 0;
  background: #f5f5f5;
  color: #888;
  text-align: center;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.15s;
  border: 1px dashed #e0e0e0;
}
.upload-btn:hover { background: #eee; color: #1f1f1f; border-color: #ccc; }
.upload-btn.uploading { opacity: 0.5; cursor: not-allowed; }
.upload-btn input { display: none; }

/* ===== 用户信息 ===== */
.user-section {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-top: 1px solid #e8e8ea;
  font-size: 12px;
}
.user-phone { color: #888; }
.user-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.btn-admin {
  padding: 4px 10px;
  background: #f0f4ff;
  border: 1px solid #c7d8fe;
  border-radius: 6px;
  color: #1e40af;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.btn-admin:hover { background: #dbeafe; border-color: #1e40af; }
.btn-logout {
  padding: 4px 12px;
  background: none;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  color: #888;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.15s;
}
.btn-logout:hover { border-color: #e03e3e; color: #e03e3e; }

/* ===== 主区域 ===== */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.chat-header {
  padding: 14px 28px;
  background: #fff;
  border-bottom: 1px solid #e8e8ea;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.chat-header h1 {
  font-size: 14px;
  font-weight: 600;
  color: #1f1f1f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-count { font-size: 11px; color: #bbb; flex-shrink: 0; }

/* ===== 消息区 ===== */
.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding: 20px 28px;
}

.welcome {
  text-align: center;
  padding: 80px 0;
  color: #ccc;
}
.welcome-icon { font-size: 32px; margin-bottom: 10px; }
.welcome p { font-size: 13px; }

.message {
  margin-bottom: 16px;
  max-width: 78%;
}
.message.user { margin-left: auto; }
.message.assistant { margin-right: auto; }

.msg-content {
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.message.user .msg-content {
  background: #1f1f1f;
  color: #fff;
  border-bottom-right-radius: 3px;
}
.message.assistant .msg-content {
  background: #fff;
  border: 1px solid #e8e8ea;
  border-bottom-left-radius: 3px;
}

.thinking { color: #bbb; }

.sources {
  margin-top: 6px;
  padding: 6px 10px;
  background: #fafafa;
  border-radius: 6px;
  font-size: 11px;
}
.source-title { color: #bbb; margin-bottom: 3px; }
.source-item { color: #888; }

/* ===== 输入区 ===== */
.input-area {
  display: flex;
  padding: 12px 28px 16px;
  background: #fff;
  border-top: 1px solid #e8e8ea;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}
.input-area input {
  flex: 1;
  padding: 9px 14px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
}
.input-area input::placeholder { color: #ccc; }
.input-area input:focus { border-color: #1f1f1f; }
.input-area input:disabled { background: #f7f7f8; }
.input-area button {
  padding: 9px 20px;
  background: #1f1f1f;
  color: #fff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: opacity 0.15s;
}
.input-area button:hover { opacity: 0.85; }
.input-area button:disabled { opacity: 0.3; cursor: not-allowed; }
.cursor { animation: blink 0.6s infinite; }
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ===== 移动端适配 ===== */
.btn-menu {
  display: none;
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #1f1f1f;
  padding: 0 4px;
  line-height: 1;
}
.chat-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.chat-header-left h1 {
  min-width: 0;
}

@media (max-width: 768px) {
  .btn-menu { display: inline-flex; }
  .sidebar-backdrop {
    display: block;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.4);
    z-index: 999;
  }
  .sidebar {
    position: fixed;
    top: 0; left: 0; bottom: 0;
    z-index: 1000;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    width: 280px;
  }
  .sidebar--open {
    transform: translateX(0);
  }
  .chat-header {
    padding: 10px 14px;
  }
  .doc-count { display: none; }
  .messages {
    padding: 12px 14px;
  }
  .message {
    max-width: 90%;
  }
  .welcome {
    padding: 40px 0;
  }
  .input-area {
    padding: 8px 14px 12px;
  }
  .input-area button {
    padding: 9px 14px;
  }
}
</style>
