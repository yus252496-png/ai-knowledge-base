<template>
  <div class="admin-page">
    <header class="admin-header">
      <div class="header-left">
        <button class="btn-back" @click="goBack" title="返回聊天">← 返回</button>
        <h2>后台管理</h2>
      </div>
      <div class="header-right">
        <span class="badge" :class="roleClass">{{ currentRole }}</span>
        <input v-model="search" class="search-input" placeholder="搜索手机号..." />
      </div>
    </header>

    <div class="admin-body">
      <table class="user-table">
        <thead>
          <tr>
            <th>手机号</th>
            <th class="sortable" @click="toggleRoleSort">角色{{ sortArrow(roleSortDir) }}</th>
            <th>密保问题</th>
            <th class="sortable" @click="toggleDateSort">注册时间{{ sortArrow(dateSortDir) }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in filteredUsers" :key="u.id">
            <td>{{ u.phone }}</td>
            <td><span class="badge" :class="'role-' + u.role">{{ roleLabel(u.role) }}</span></td>
            <td>{{ u.security_question || '-' }}</td>
            <td>{{ formatDate(u.created_at) }}</td>
            <td class="actions">
              <button class="btn-sm" @click="viewDetail(u.id)">详情</button>
              <button class="btn-sm" @click="openEdit(u)">编辑</button>
              <button v-if="u.role !== 'super_admin'" class="btn-sm btn-danger" @click="confirmDelete(u)" :disabled="u.id === myUserId">删除</button>
              <button v-if="isSuperAdmin && u.id !== myUserId" class="btn-sm btn-role" @click="toggleRole(u)">
                {{ u.role === 'admin' ? '取消管理员' : '设为管理员' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="filteredUsers.length === 0" class="empty">没有找到匹配的用户</div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="showDetail" class="modal-overlay" @click.self="showDetail = false">
      <div class="modal" style="width: 700px;">
        <div class="modal-header">
          <h3>用户详情</h3>
          <button class="btn-close" @click="showDetail = false">✕</button>
        </div>
        <div class="modal-body">
          <section class="detail-section">
            <h4>基本信息</h4>
            <div class="info-grid">
              <div><label>用户 ID</label><span>{{ detailUser?.user?.id }}</span></div>
              <div><label>手机号</label><span>{{ detailUser?.user?.phone }}</span></div>
              <div><label>角色</label><span>{{ roleLabel(detailUser?.user?.role) }}</span></div>
              <div><label>密保问题</label><span>{{ detailUser?.user?.security_question || '-' }}</span></div>
              <div><label>密保答案</label><span>{{ detailUser?.user?.security_answer || '-' }}</span></div>
              <div><label>注册时间</label><span>{{ formatDate(detailUser?.user?.created_at) }}</span></div>
            </div>
          </section>

          <section class="detail-section">
            <h4>上传的文件（{{ detailUser?.files?.length || 0 }}）</h4>
            <div v-if="detailUser?.files?.length" class="file-list">
              <div v-for="f in detailUser.files" :key="f.doc_id" class="file-item">
                <span class="file-name">{{ f.file_name }}</span>
                <span class="file-meta">{{ f.total_chunks }} 段</span>
                <button class="btn-sm" @click="previewFile(detailUser.user.id, f.doc_id, f.file_name)">预览</button>
              </div>
            </div>
            <div v-else class="empty">暂无文件</div>
          </section>

          <section class="detail-section">
            <h4>对话历史（{{ detailUser?.conversations?.length || 0 }}）</h4>
            <div v-if="detailUser?.conversations?.length" class="conv-list">
              <div
                v-for="c in detailUser.conversations"
                :key="c.id"
                class="conv-item-detail"
                :class="{ active: convDetailId === c.id }"
                @click="viewConversation(c.id)"
              >
                <div class="conv-header">
                  <span class="conv-title-detail">{{ c.title }}</span>
                  <span class="conv-date">{{ formatDate(c.created_at) }}</span>
                </div>
                <span class="conv-msgs">{{ c.message_count }} 条消息</span>
              </div>
            </div>
            <div v-else class="empty">暂无对话</div>
            <!-- 对话详情 -->
            <div v-if="convMessages.length" class="conv-detail">
              <div class="conv-detail-header">
                <h5>{{ convDetailTitle }}</h5>
              </div>
              <div class="conv-messages">
                <div v-for="(m, mi) in convMessages" :key="mi" class="conv-msg" :class="m.role">
                  <div class="conv-msg-label">{{ m.role === 'user' ? '用户' : 'AI' }}</div>
                  <div class="conv-msg-content">{{ m.content }}</div>
                  <div v-if="m.sources && m.sources.length" class="conv-msg-sources">
                    <span v-for="(s, si) in m.sources" :key="si" class="conv-source-tag">{{ s.file_name }} p{{ s.page }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>

    <!-- 编辑弹窗 -->
    <div v-if="showEdit" class="modal-overlay" @click.self="showEdit = false">
      <div class="modal">
        <div class="modal-header">
          <h3>编辑用户</h3>
          <button class="btn-close" @click="showEdit = false">✕</button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label>手机号</label>
            <input v-model="editForm.phone" type="text" readonly />
          </div>
          <div class="field">
            <label>密保问题</label>
            <select v-model="editForm.security_question" class="auth-select">
              <option value="">不修改</option>
              <option v-for="q in securityQuestions" :key="q" :value="q">{{ q }}</option>
            </select>
          </div>
          <div v-if="editForm.security_question" class="field">
            <label>密保答案</label>
            <input v-model="editForm.security_answer" type="text" placeholder="请输入新的答案" />
          </div>
          <div class="field">
            <label>登入密码</label>
            <input v-model="editForm.password" type="password" placeholder="留空则不修改密码" />
          </div>
          <div v-if="editError" class="error-msg">{{ editError }}</div>
          <div v-if="editSuccess" class="success-msg">{{ editSuccess }}</div>
          <div class="modal-actions">
            <button class="auth-btn" @click="saveEdit" :disabled="editLoading">{{ editLoading ? '保存中...' : '保存' }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- PDF 预览弹窗 -->
    <div v-if="showPdf" class="modal-overlay" @click.self="showPdf = false">
      <div class="modal pdf-modal" :class="{ 'pdf-fullscreen': pdfFullscreen }">
        <div class="modal-header">
          <h3>{{ pdfFileName }}</h3>
          <div class="header-actions">
            <button class="btn-sm" @click="pdfFullscreen = !pdfFullscreen">
              {{ pdfFullscreen ? '退出全屏' : '全屏' }}
            </button>
            <button class="btn-close" @click="showPdf = false">✕</button>
          </div>
        </div>
        <div class="modal-body" :style="{ height: pdfFullscreen ? '90vh' : '70vh' }">
          <iframe v-if="pdfBlobUrl" :src="pdfBlobUrl" class="pdf-frame" frameborder="0"></iframe>
          <div v-else class="loading">加载中...</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { adminListUsers, adminGetUser, adminUpdateUser, adminDeleteUser, adminSetRole, getAdminFileBlobUrl, getCurrentUser, getConversation } from '../api/index.js'
import { authState } from '../stores/auth.js'
import { getSecurityQuestions } from '../api/index.js'

const router = useRouter()
const search = ref('')
const users = ref([])
const roleSortDir = ref(null) // null = 不排序, 'asc', 'desc'
const dateSortDir = ref(null)
const myUserId = computed(() => authState.userId.value)
const isSuperAdmin = computed(() => authState.role.value === 'super_admin')
const isAdmin = computed(() => authState.role.value === 'admin' || authState.role.value === 'super_admin')
const securityQuestions = ref([])

const currentRole = computed(() => {
  const r = authState.role.value
  if (r === 'super_admin') return '超级管理员'
  if (r === 'admin') return '管理员'
  return '用户'
})
const roleClass = computed(() => 'role-' + authState.role.value)

function roleSortWeight(role) {
  if (role === 'super_admin') return 0
  if (role === 'admin') return 1
  return 2
}

const filteredUsers = computed(() => {
  let list = users.value
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter(u => (u.phone || u.phone_masked).toLowerCase().includes(q))
  }
  if (roleSortDir.value) {
    const dir = roleSortDir.value === 'asc' ? 1 : -1
    list = [...list].sort((a, b) => (roleSortWeight(a.role) - roleSortWeight(b.role)) * dir)
  }
  if (dateSortDir.value) {
    const dir = dateSortDir.value === 'asc' ? 1 : -1
    list = [...list].sort((a, b) => (new Date(a.created_at) - new Date(b.created_at)) * dir)
  }
  return list
})

function toggleRoleSort() {
  dateSortDir.value = null
  if (!roleSortDir.value) roleSortDir.value = 'asc'
  else if (roleSortDir.value === 'asc') roleSortDir.value = 'desc'
  else roleSortDir.value = null
}

function toggleDateSort() {
  roleSortDir.value = null
  if (!dateSortDir.value) dateSortDir.value = 'asc'
  else if (dateSortDir.value === 'asc') dateSortDir.value = 'desc'
  else dateSortDir.value = null
}

function sortArrow(dir) {
  if (!dir) return ''
  return dir === 'asc' ? ' ↑' : ' ↓'
}

function roleLabel(role) {
  if (role === 'super_admin') return '超级管理员'
  if (role === 'admin') return '管理员'
  return '用户'
}

function formatDate(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function goBack() {
  router.push('/')
}

// 详情
const showDetail = ref(false)
const detailUser = ref(null)
const detailLoading = ref(false)

async function viewDetail(userId) {
  detailLoading.value = true
  showDetail.value = true
  try {
    const res = await adminGetUser(userId)
    detailUser.value = res.data
  } catch {
    detailUser.value = null
  } finally {
    detailLoading.value = false
  }
}

// 编辑
const showEdit = ref(false)
const editForm = ref({ phone: '', security_question: '', security_answer: '', password: '' })
const editUserId = ref('')
const editLoading = ref(false)
const editError = ref('')
const editSuccess = ref('')

function openEdit(user) {
  editUserId.value = user.id
  editForm.value = { phone: user.phone || user.phone_masked, security_question: user.security_question || '', security_answer: user.security_answer || '', password: '' }
  editError.value = ''
  editSuccess.value = ''
  showEdit.value = true
}

async function saveEdit() {
  editLoading.value = true
  editError.value = ''
  editSuccess.value = ''
  try {
    const data = {}
    if (editForm.value.phone) data.phone = editForm.value.phone
    if (editForm.value.security_question) {
      data.security_question = editForm.value.security_question
      if (editForm.value.security_answer) data.security_answer = editForm.value.security_answer
    }
    if (editForm.value.password) data.password = editForm.value.password
    await adminUpdateUser(editUserId.value, data)
    showEdit.value = false
    await loadUsers()
  } catch (e) {
    editError.value = '保存失败，请重试'
  } finally {
    editLoading.value = false
  }
}

// PDF 预览
const showPdf = ref(false)
const pdfBlobUrl = ref('')
const pdfFileName = ref('')
const pdfFullscreen = ref(false)

async function previewFile(userId, docId, fileName) {
  showPdf.value = true
  pdfFullscreen.value = false
  pdfFileName.value = fileName
  pdfBlobUrl.value = ''
  try {
    pdfBlobUrl.value = await getAdminFileBlobUrl(userId, docId)
  } catch {
    pdfBlobUrl.value = ''
  }
}

// 对话详情
const convDetailId = ref('')
const convDetailTitle = ref('')
const convMessages = ref([])

async function viewConversation(convId) {
  if (convDetailId.value === convId) {
    convDetailId.value = ''
    convMessages.value = []
    return
  }
  convDetailId.value = convId
  try {
    const res = await getConversation(convId)
    const conv = res.data
    convDetailTitle.value = conv.title
    convMessages.value = conv.messages || []
  } catch {
    convMessages.value = []
  }
}

// 删除
async function confirmDelete(user) {
  if (!confirm(`确定要删除用户 ${user.phone_masked} 吗？此操作不可恢复。`)) return
  try {
    await adminDeleteUser(user.id)
    await loadUsers()
  } catch {
    alert('删除失败')
  }
}

// 角色切换
async function toggleRole(user) {
  const newRole = user.role === 'admin' ? 'user' : 'admin'
  const action = newRole === 'admin' ? '设为管理员' : '取消管理员'
  if (!confirm(`确定要${action} (${user.phone_masked}) 吗？`)) return
  try {
    await adminSetRole(user.id, newRole)
    await loadUsers()
  } catch {
    alert('操作失败')
  }
}

// 加载
async function loadUsers() {
  try {
    const res = await adminListUsers()
    users.value = res.data || []
  } catch {
    users.value = []
  }
}

async function loadMyRole() {
  try {
    const res = await getCurrentUser()
    if (res.data.role) {
      authState.setRole(res.data.role)
    }
  } catch {}
}

onMounted(async () => {
  await loadMyRole()
  await loadUsers()
  try {
    const res = await getSecurityQuestions()
    securityQuestions.value = res.data.questions || []
  } catch {}
})
</script>

<style scoped>
.admin-page {
  min-height: 100vh;
  background: #f7f7f8;
  font-size: 13px;
  color: #1f1f1f;
}
.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #fff;
  border-bottom: 1px solid #e8e8ea;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.btn-back {
  background: none;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 5px 12px;
  cursor: pointer;
  font-size: 12px;
  color: #888;
  transition: all 0.15s;
}
.btn-back:hover { border-color: #1f1f1f; color: #1f1f1f; }
.search-input {
  padding: 6px 12px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  font-size: 12px;
  outline: none;
  width: 200px;
}
.search-input:focus { border-color: #1f1f1f; }

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}
.role-super_admin { background: #fef3c7; color: #92400e; }
.role-admin { background: #dbeafe; color: #1e40af; }
.role-user { background: #f3f4f6; color: #6b7280; }

.admin-body {
  padding: 16px 20px;
}

.user-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.user-table th {
  background: #fafafa;
  padding: 10px 14px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border-bottom: 1px solid #e8e8ea;
}
.user-table th.sortable {
  cursor: pointer;
  user-select: none;
  transition: color 0.15s;
}
.user-table th.sortable:hover { color: #1f1f1f; }
.user-table td {
  padding: 10px 14px;
  border-bottom: 1px solid #f3f3f5;
  vertical-align: middle;
}
.user-table tr:last-child td { border-bottom: none; }
.user-table tr:hover { background: #fafafa; }

.actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.btn-sm {
  padding: 4px 10px;
  border: 1px solid #e0e0e0;
  border-radius: 5px;
  background: #fff;
  cursor: pointer;
  font-size: 11px;
  color: #555;
  transition: all 0.15s;
  white-space: nowrap;
}
.btn-sm:hover { border-color: #1f1f1f; color: #1f1f1f; }
.btn-sm:disabled { opacity: 0.3; cursor: not-allowed; }
.btn-danger { color: #e03e3e; }
.btn-danger:hover { border-color: #e03e3e; background: #fef2f2; }
.btn-role { color: #1e40af; }
.btn-role:hover { border-color: #1e40af; background: #dbeafe; }

.empty {
  text-align: center;
  padding: 40px;
  color: #bbb;
  font-size: 13px;
}

/* 弹窗 */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: #fff;
  border-radius: 12px;
  width: 460px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 30px rgba(0,0,0,0.12);
}
.pdf-modal {
  width: 800px;
  max-width: 90vw;
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #e8e8ea;
}
.modal-header h3 {
  font-size: 14px;
  font-weight: 600;
}
.btn-close {
  background: none;
  border: none;
  font-size: 16px;
  color: #bbb;
  cursor: pointer;
  padding: 4px;
  line-height: 1;
}
.btn-close:hover { color: #1f1f1f; }
.modal-body {
  padding: 20px;
  overflow-y: auto;
}
.modal-actions {
  margin-top: 16px;
  text-align: right;
}

.detail-section {
  margin-bottom: 20px;
}
.detail-section h4 {
  font-size: 12px;
  font-weight: 600;
  color: #888;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid #f0f0f0;
}
.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.info-grid div {
  padding: 6px 0;
}
.info-grid label {
  display: block;
  font-size: 10px;
  color: #bbb;
  margin-bottom: 2px;
}
.info-grid span {
  font-size: 13px;
  color: #1f1f1f;
}

.file-list, .conv-list {
  max-height: 200px;
  overflow-y: auto;
}
.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
}
.file-item:hover { background: #f5f5f5; }
.file-name {
  flex: 1;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-meta {
  font-size: 10px;
  color: #bbb;
}

.conv-item-detail {
  padding: 8px;
  border-radius: 6px;
  margin-bottom: 4px;
  cursor: pointer;
}
.conv-item-detail:hover { background: #f5f5f5; }
.conv-item-detail.active { background: #e8e8ea; }
.conv-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.conv-title-detail {
  font-size: 12px;
  font-weight: 500;
}
.conv-date {
  font-size: 10px;
  color: #bbb;
}
.conv-msgs {
  font-size: 10px;
  color: #bbb;
}

.pdf-frame {
  width: 100%;
  height: 100%;
  border-radius: 4px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pdf-fullscreen {
  width: 95vw !important;
  max-width: 95vw !important;
}

/* 对话详情 */
.conv-detail {
  margin-top: 12px;
  border-top: 1px solid #e8e8ea;
  padding-top: 12px;
}
.conv-detail-header h5 {
  font-size: 12px;
  color: #1f1f1f;
  font-weight: 600;
  margin-bottom: 8px;
}
.conv-messages {
  max-height: 300px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.conv-msg {
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
}
.conv-msg.user {
  background: #f5f5f5;
  margin-left: 20px;
}
.conv-msg.assistant {
  background: #f0f7ff;
  margin-right: 20px;
}
.conv-msg-label {
  font-size: 10px;
  font-weight: 600;
  color: #888;
  margin-bottom: 3px;
}
.conv-msg-content {
  white-space: pre-wrap;
  word-break: break-word;
}
.conv-msg-sources {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.conv-source-tag {
  font-size: 10px;
  padding: 1px 6px;
  background: #e8e8ea;
  border-radius: 3px;
  color: #888;
}

.field {
  margin-bottom: 14px;
}
.field label {
  display: block;
  font-size: 12px;
  color: #888;
  margin-bottom: 4px;
}
.field input, .field select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}
.field input:focus, .field select:focus {
  border-color: #1f1f1f;
}
.field input[readonly] {
  background: #f7f7f8;
  cursor: not-allowed;
}
.auth-select {
  background: #fff;
  cursor: pointer;
}

.error-msg {
  font-size: 12px;
  color: #e03e3e;
  margin-bottom: 10px;
  padding: 6px 10px;
  background: #fef2f2;
  border-radius: 6px;
}
.success-msg {
  font-size: 12px;
  color: #1a8a3f;
  margin-bottom: 10px;
  padding: 6px 10px;
  background: #f0fdf4;
  border-radius: 6px;
}
.auth-btn {
  padding: 8px 24px;
  background: #1f1f1f;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: opacity 0.15s;
}
.auth-btn:hover { opacity: 0.85; }
.auth-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.loading { text-align: center; padding: 40px; color: #bbb; }

/* ===== 移动端适配 ===== */
@media (max-width: 768px) {
  .admin-header {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    padding: 10px 14px;
  }
  .header-left h2 { font-size: 14px; }
  .header-right {
    flex-wrap: wrap;
    gap: 6px;
  }
  .search-input {
    width: 100%;
    flex: 1;
    min-width: 0;
  }
  .admin-body {
    padding: 10px 8px;
  }
  .user-table {
    font-size: 12px;
  }
  .user-table th,
  .user-table td {
    padding: 8px 8px;
  }
  .user-table td:last-child {
    min-width: 180px;
  }
  .actions {
    gap: 4px;
  }
  .actions .btn-sm {
    padding: 3px 7px;
    font-size: 10px;
  }
  /* 表格容器横向滚动 */
  .admin-body {
    overflow-x: auto;
  }
  .user-table {
    min-width: 600px;
  }
  /* 弹窗全屏 */
  .modal {
    width: 100% !important;
    max-width: 100% !important;
    max-height: 100vh !important;
    height: 100vh;
    border-radius: 0;
    margin: 0;
  }
  .modal-overlay {
    align-items: flex-end;
  }
  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
