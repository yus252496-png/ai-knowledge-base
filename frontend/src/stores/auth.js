import { reactive, computed } from 'vue'

const state = reactive({
  token: localStorage.getItem('token') || null,
  userId: localStorage.getItem('userId') || null,
  phone: localStorage.getItem('phone') || null,
  role: localStorage.getItem('role') || null,
})

export const authState = {
  token: computed(() => state.token),
  userId: computed(() => state.userId),
  phone: computed(() => state.phone),
  role: computed(() => state.role),
  isLoggedIn: computed(() => !!state.token),
  isAdmin: computed(() => state.role === 'admin' || state.role === 'super_admin'),
  isSuperAdmin: computed(() => state.role === 'super_admin'),

  login(token, userId, phone, role) {
    state.token = token
    state.userId = userId
    state.phone = phone
    state.role = role
    localStorage.setItem('token', token)
    localStorage.setItem('userId', userId)
    localStorage.setItem('phone', phone)
    localStorage.setItem('role', role)
  },

  setRole(role) {
    state.role = role
    localStorage.setItem('role', role)
  },

  logout() {
    state.token = null
    state.userId = null
    state.phone = null
    state.role = null
    localStorage.removeItem('token')
    localStorage.removeItem('userId')
    localStorage.removeItem('phone')
    localStorage.removeItem('role')
  },
}
