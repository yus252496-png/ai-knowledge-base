import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: `${BASE}/api`,
  timeout: 120000,
})

// 文档
export function uploadDocument(file) {
  const form = new FormData()
  form.append('file', file)
  return api.post('/upload', form)
}
export function listDocuments() {
  return api.get('/documents')
}
export function deleteDocument(docId) {
  return api.delete(`/documents/${docId}`)
}
export function clearDocuments() {
  return api.delete('/documents')
}

// 非流式聊天（fallback）
export function chat(question, conversationId = null) {
  return api.post('/chat', { question, conversation_id: conversationId })
}

// 流式聊天：回调方式，返回 AbortController 以便取消
export function chatStream(question, conversationId, callbacks) {
  const controller = new AbortController()

  // 类型: 'per-word' 流式输出关键词，'typewriter' 逐字出现
  const mode = 'typewriter'

  fetch(`${BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, conversation_id: conversationId }),
    signal: controller.signal,
  }).then(async (response) => {
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullText = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6).trim()
        if (!payload) continue

        try {
          const msg = JSON.parse(payload)

          if (mode === 'typewriter' && msg.type === 'token') {
            // dashscope 返回的是累计文本（非 delta），直接赋值
            fullText = msg.data
            callbacks.onMessage?.({ type: 'fulltext', data: fullText })
          } else {
            // sources / done / error 照常
            callbacks.onMessage?.(msg)
          }
        } catch {}
      }
    }

    callbacks.onComplete?.()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      callbacks.onError?.(err)
    }
  })

  return controller
}

// 会话管理
export function listConversations() {
  return api.get('/conversations')
}
export function createConversation() {
  return api.post('/conversations')
}
export function getConversation(convId) {
  return api.get(`/conversations/${convId}`)
}
export function deleteConversation(convId) {
  return api.delete(`/conversations/${convId}`)
}
export function getActiveConversation() {
  return api.get('/conversations/active/latest')
}
