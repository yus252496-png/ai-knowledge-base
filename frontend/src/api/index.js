import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: `${BASE}/api`,
  timeout: 120000,
})

// JWT 请求拦截器
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401 响应拦截器
api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('userId')
      localStorage.removeItem('phone')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// 认证
export function register(phone, password, securityQuestion, securityAnswer) {
  const params = new URLSearchParams()
  params.append('phone', phone)
  params.append('password', password)
  params.append('security_question', securityQuestion)
  params.append('security_answer', securityAnswer)
  return api.post('/auth/register', params)
}

export function getCaptcha() {
  return api.get('/auth/captcha')
}

export function login(phone, password, captchaId, captchaCode) {
  const params = new URLSearchParams()
  params.append('phone', phone)
  params.append('password', password)
  params.append('captcha_id', captchaId)
  params.append('captcha_code', captchaCode)
  return api.post('/auth/login', params)
}

// 密保 / 忘记密码
export function getSecurityQuestions() {
  return api.get('/auth/security-questions')
}

export function forgotPassword(phone) {
  const params = new URLSearchParams()
  params.append('phone', phone)
  return api.post('/auth/forgot-password', params)
}

export function verifySecurity(phone, answer) {
  const params = new URLSearchParams()
  params.append('phone', phone)
  params.append('answer', answer)
  return api.post('/auth/verify-security', params)
}

export function resetPassword(resetToken, newPassword) {
  const params = new URLSearchParams()
  params.append('reset_token', resetToken)
  params.append('new_password', newPassword)
  return api.post('/auth/reset-password', params)
}

// 文档
export function uploadDocument(file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  return api.post('/upload', form, {
    onUploadProgress(progressEvent) {
      if (onProgress && progressEvent.total) {
        const pct = Math.round((progressEvent.loaded / progressEvent.total) * 100)
        onProgress(pct)
      }
    },
  })
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

// 流式聊天
export function chatStream(question, conversationId, callbacks) {
  const controller = new AbortController()

  fetch(`${BASE}/api/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${localStorage.getItem('token')}`,
    },
    body: JSON.stringify({ question, conversation_id: conversationId }),
    signal: controller.signal,
  }).then(async (response) => {
    if (response.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('userId')
      localStorage.removeItem('phone')
      window.location.href = '/login'
      return
    }

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

          if (msg.type === 'token') {
            fullText += msg.data
            callbacks.onMessage?.({ type: 'fulltext', data: fullText })
          } else {
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

// 管理后台
export function adminListUsers() {
  return api.get('/admin/users')
}
export function adminGetUser(userId) {
  return api.get(`/admin/users/${userId}`)
}
export function adminUpdateUser(userId, data) {
  return api.put(`/admin/users/${userId}`, data)
}
export function adminDeleteUser(userId) {
  return api.delete(`/admin/users/${userId}`)
}
export function adminSetRole(userId, role) {
  const params = new URLSearchParams()
  params.append('role', role)
  return api.post(`/admin/users/${userId}/role`, params)
}
export function adminFileUrl(userId, docId) {
  const base = import.meta.env.VITE_API_URL || ''
  const token = localStorage.getItem('token')
  return `${base}/api/admin/files/${userId}/${docId}?token=${token}`
}
export function getAdminFileBlobUrl(userId, docId) {
  const base = import.meta.env.VITE_API_URL || ''
  const token = localStorage.getItem('token')
  return fetch(`${base}/api/admin/files/${userId}/${docId}`, {
    headers: { 'Authorization': `Bearer ${token}` },
  }).then(res => {
    if (!res.ok) throw new Error('Failed to fetch file')
    return res.blob()
  }).then(blob => URL.createObjectURL(blob))
}
export function getCurrentUser() {
  return api.get('/auth/me')
}
