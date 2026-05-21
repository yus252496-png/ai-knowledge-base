import { reactive, computed } from 'vue'

const state = reactive({
  token: localStorage.getItem('token') || null,
  userId: localStorage.getItem('userId') || null,
  phone: localStorage.getItem('phone') || null,
})

export const authState = {
  token: computed(() => state.token),
  userId: computed(() => state.userId),
  phone: computed(() => state.phone),
  isLoggedIn: computed(() => !!state.token),

  login(token, userId, phone) {
    state.token = token
    state.userId = userId
    state.phone = phone
    localStorage.setItem('token', token)
    localStorage.setItem('userId', userId)
    localStorage.setItem('phone', phone)
  },

  logout() {
    state.token = null
    state.userId = null
    state.phone = null
    localStorage.removeItem('token')
    localStorage.removeItem('userId')
    localStorage.removeItem('phone')
  },
}
