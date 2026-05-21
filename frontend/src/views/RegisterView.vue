<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-header">
        <div class="auth-icon">☁</div>
        <h2>创建账户</h2>
        <p class="auth-subtitle">输入手机号注册新账户</p>
      </div>
      <form @submit.prevent="handleRegister" class="auth-form">
        <div class="field">
          <label>手机号</label>
          <input
            v-model="phone"
            type="tel"
            placeholder="11 位手机号"
            maxlength="11"
            :disabled="loading"
          />
          <span v-if="phone && phone.length !== 11" class="field-hint">手机号应为 11 位</span>
        </div>
        <div class="field">
          <label>密码</label>
          <input
            v-model="password"
            type="password"
            placeholder="至少 6 位"
            :disabled="loading"
          />
          <span v-if="password && password.length < 6" class="field-hint">密码至少 6 位</span>
        </div>
        <div class="field">
          <label>确认密码</label>
          <input
            v-model="confirmPassword"
            type="password"
            placeholder="再次输入密码"
            :disabled="loading"
          />
          <span v-if="confirmPassword && password !== confirmPassword" class="field-hint">两次密码不一致</span>
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <button type="submit" class="auth-btn" :disabled="!canSubmit || loading">
          {{ loading ? '注册中...' : '注册' }}
        </button>
      </form>
      <div class="auth-link">
        已有账户？<router-link to="/login">立即登录</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { register } from '../api/index.js'
import { authState } from '../stores/auth.js'

const router = useRouter()

const phone = ref('')
const password = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const errorMsg = ref('')

const canSubmit = computed(() => {
  return phone.value.length === 11
    && password.value.length >= 6
    && password.value === confirmPassword.value
    && !loading.value
})

async function handleRegister() {
  if (!canSubmit.value) return
  loading.value = true
  errorMsg.value = ''

  try {
    const res = await register(phone.value, password.value)
    if (res.data.token) {
      authState.login(res.data.token, res.data.user_id, res.data.phone_masked)
      router.push('/')
    }
  } catch (e) {
    if (e.response?.status === 409) {
      errorMsg.value = '该手机号已注册'
    } else if (e.response?.status === 422) {
      errorMsg.value = '手机号或密码格式不正确'
    } else {
      errorMsg.value = '注册失败，请重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #f7f7f8;
}
.auth-card {
  width: 360px;
  background: #fff;
  border-radius: 12px;
  padding: 32px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.auth-header {
  text-align: center;
  margin-bottom: 24px;
}
.auth-icon {
  font-size: 36px;
  margin-bottom: 8px;
  color: #888;
}
.auth-header h2 {
  font-size: 16px;
  font-weight: 600;
  color: #1f1f1f;
  margin-bottom: 4px;
}
.auth-subtitle {
  font-size: 12px;
  color: #bbb;
}
.auth-form .field {
  margin-bottom: 16px;
}
.auth-form label {
  display: block;
  font-size: 12px;
  color: #888;
  margin-bottom: 4px;
}
.auth-form input {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
  box-sizing: border-box;
}
.auth-form input:focus {
  border-color: #1f1f1f;
}
.auth-form input:disabled {
  background: #f7f7f8;
}
.field-hint {
  display: block;
  font-size: 11px;
  color: #e03e3e;
  margin-top: 2px;
}
.error-msg {
  font-size: 12px;
  color: #e03e3e;
  margin-bottom: 12px;
  padding: 6px 10px;
  background: #fef2f2;
  border-radius: 6px;
}
.auth-btn {
  width: 100%;
  padding: 10px;
  background: #1f1f1f;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s;
}
.auth-btn:hover { opacity: 0.85; }
.auth-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.auth-link {
  text-align: center;
  margin-top: 16px;
  font-size: 12px;
  color: #bbb;
}
.auth-link a {
  color: #1f1f1f;
  text-decoration: none;
  font-weight: 500;
}
.auth-link a:hover { text-decoration: underline; }
</style>
