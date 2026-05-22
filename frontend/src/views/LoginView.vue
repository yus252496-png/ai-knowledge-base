<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-header">
        <div class="auth-icon">☁</div>
        <h2>知识库问答</h2>
        <p class="auth-subtitle">登录到您的账户</p>
      </div>
      <form @submit.prevent="handleLogin" class="auth-form">
        <div class="field">
          <label>手机号</label>
          <input
            v-model="phone"
            type="tel"
            placeholder="请输入手机号"
            maxlength="11"
            :disabled="loading"
          />
        </div>
        <div class="field">
          <label>密码</label>
          <input
            v-model="password"
            type="password"
            placeholder="请输入密码"
            :disabled="loading"
          />
        </div>
        <div class="field captcha-field">
          <label>验证码</label>
          <div class="captcha-row">
            <input
              v-model="captchaCode"
              type="text"
              placeholder="4位数字"
              maxlength="4"
              :disabled="loading"
            />
            <img
              v-if="captchaImage"
              :src="captchaImage"
              class="captcha-img"
              @click="loadCaptcha"
              title="点击刷新验证码"
            />
          </div>
        </div>
        <div v-if="errorMsg" class="error-msg" :class="{ 'error-locked': isLocked }">
          {{ errorMsg }}
        </div>
        <button type="submit" class="auth-btn" :disabled="!canSubmit || loading">
          {{ loading ? '登录中...' : '登录' }}
        </button>
        <div class="forgot-link">
          <router-link to="/forgot-password">忘记密码？</router-link>
        </div>
      </form>
      <div class="auth-link">
        还没有账户？<router-link to="/register">立即注册</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getCaptcha, login } from '../api/index.js'
import { authState } from '../stores/auth.js'

const router = useRouter()

const phone = ref('')
const password = ref('')
const captchaId = ref('')
const captchaCode = ref('')
const captchaImage = ref('')
const loading = ref(false)
const errorMsg = ref('')
const isLocked = ref(false)

const canSubmit = computed(() => {
  return phone.value.length === 11 && password.value.length >= 6 && captchaCode.value.length === 4 && !loading.value
})

async function loadCaptcha() {
  try {
    const res = await getCaptcha()
    captchaId.value = res.data.captcha_id
    captchaImage.value = res.data.image
  } catch {
    errorMsg.value = '获取验证码失败，请重试'
  }
}

async function handleLogin() {
  if (!canSubmit.value) return
  loading.value = true
  errorMsg.value = ''
  isLocked.value = false

  try {
    const res = await login(phone.value, password.value, captchaId.value, captchaCode.value)
    if (res.data.error === 'captcha_wrong') {
      errorMsg.value = '验证码错误'
      captchaCode.value = ''
      await loadCaptcha()
    } else if (res.data.error === 'locked') {
      isLocked.value = true
      const mins = res.data.remaining_minutes || 60
      errorMsg.value = `账号已锁定，剩余 ${mins} 分钟`
    } else if (res.data.error === 'login_failed') {
      errorMsg.value = res.data.detail || '手机号或密码错误'
      captchaCode.value = ''
      await loadCaptcha()
    } else if (res.data.error === 'not_registered') {
      errorMsg.value = '该手机号未注册，请先注册'
      captchaCode.value = ''
      await loadCaptcha()
    } else if (res.data.token) {
      authState.login(res.data.token, res.data.user_id, res.data.phone_masked, res.data.role)
      router.push('/')
    }
  } catch (e) {
    if (e.response?.status === 422) {
      errorMsg.value = '请输入正确的手机号和验证码'
    } else {
      errorMsg.value = '网络错误，请重试'
    }
    await loadCaptcha()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadCaptcha()
})
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
.captcha-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.captcha-row input {
  flex: 1;
}
.captcha-img {
  height: 36px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid #e0e0e0;
}
.error-msg {
  font-size: 12px;
  color: #e03e3e;
  margin-bottom: 12px;
  padding: 6px 10px;
  background: #fef2f2;
  border-radius: 6px;
}
.error-msg.error-locked {
  color: #e67e22;
  background: #fef9ef;
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
.forgot-link {
  text-align: center;
  margin-top: 12px;
  font-size: 12px;
}
.forgot-link a {
  color: #888;
  text-decoration: none;
}
.forgot-link a:hover { color: #1f1f1f; text-decoration: underline; }

/* 移动端适配 */
@media (max-width: 640px) {
  .auth-card {
    width: 100%;
    max-width: 100%;
    min-height: 100vh;
    border-radius: 0;
    box-shadow: none;
    padding: 24px 20px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  .auth-page {
    align-items: stretch;
  }
}
</style>
