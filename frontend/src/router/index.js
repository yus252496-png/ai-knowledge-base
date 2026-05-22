import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import ForgotPasswordView from '../views/ForgotPasswordView.vue'
import ChatView from '../views/ChatView.vue'
import AdminView from '../views/AdminView.vue'

const routes = [
  { path: '/login', name: 'login', component: LoginView },
  { path: '/register', name: 'register', component: RegisterView },
  { path: '/forgot-password', name: 'forgot-password', component: ForgotPasswordView },
  { path: '/', name: 'chat', component: ChatView, meta: { requiresAuth: true } },
  { path: '/admin', name: 'admin', component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  const role = localStorage.getItem('role')
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else if (to.meta.requiresAdmin && role !== 'admin' && role !== 'super_admin') {
    next('/')
  } else if ((to.path === '/login' || to.path === '/register' || to.path === '/forgot-password') && token) {
    next('/')
  } else {
    next()
  }
})

export default router
