<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-header">
        <div class="auth-icon">☁</div>
        <h2>忘记密码</h2>
        <p class="auth-subtitle">{{ stepTitle }}</p>
      </div>

      <!-- 第一步：输入手机号 -->
      <form v-if="step === 1" @submit.prevent="handleStep1" class="auth-form">
        <div class="field">
          <label>手机号</label>
          <input v-model="phone" type="tel" placeholder="11 位手机号" maxlength="11" :disabled="loading" />
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <button type="submit" class="auth-btn" :disabled="phone.length !== 11 || loading">
          {{ loading ? '验证中...' : '下一步' }}
        </button>
      </form>

      <!-- 第二步：回答密保问题 -->
      <form v-else-if="step === 2" @submit.prevent="handleStep2" class="auth-form">
        <div class="field">
          <label>密保问题</label>
          <div class="question-display">{{ securityQuestion }}</div>
        </div>
        <div class="field">
          <label>您的答案</label>
          <input v-model="answer" type="text" placeholder="请输入您的答案" :disabled="loading" />
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <button type="submit" class="auth-btn" :disabled="!answer.trim() || loading">
          {{ loading ? '验证中...' : '验证' }}
        </button>
      </form>

      <!-- 第三步：设置新密码 -->
      <form v-else-if="step === 3" @submit.prevent="handleStep3" class="auth-form">
        <div class="field">
          <label>新密码</label>
          <input v-model="newPassword" type="password" placeholder="至少 6 位" :disabled="loading" />
          <span v-if="newPassword && newPassword.length < 6" class="field-hint">密码至少 6 位</span>
        </div>
        <div class="field">
          <label>确认新密码</label>
          <input v-model="confirmPassword" type="password" placeholder="再次输入密码" :disabled="loading" />
          <span v-if="confirmPassword && newPassword !== confirmPassword" class="field-hint">两次密码不一致</span>
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <div v-if="successMsg" class="success-msg">{{ successMsg }}</div>
        <button type="submit" class="auth-btn" :disabled="!canSubmit || loading">
          {{ loading ? '重置中...' : '重置密码' }}
        </button>
      </form>

      <div class="auth-link">
        <router-link to="/login">返回登录</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { forgotPassword, verifySecurity, resetPassword } from '../api/index.js'

const router = useRouter()

const step = ref(1)
const phone = ref('')
const securityQuestion = ref('')
const phoneMasked = ref('')
const resetToken = ref('')
const answer = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const errorMsg = ref('')
const successMsg = ref('')

const stepTitle = computed(() => {
  if (step.value === 1) return '输入注册时使用的手机号'
  if (step.value === 2) return `验证密保问题（${phoneMasked.value}）`
  return '设置新密码'
})

const canSubmit = computed(() => {
  return newPassword.value.length >= 6
    && newPassword.value === confirmPassword.value
    && !loading.value
})

async function handleStep1() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await forgotPassword(phone.value)
    if (res.data.error === 'not_found') {
      errorMsg.value = '该手机号未注册'
    } else if (res.data.error === 'no_security') {
      errorMsg.value = '该账号未设置密保问题'
    } else {
      securityQuestion.value = res.data.security_question
      phoneMasked.value = res.data.phone_masked
      step.value = 2
    }
  } catch {
    errorMsg.value = '网络错误，请重试'
  } finally {
    loading.value = false
  }
}

async function handleStep2() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await verifySecurity(phone.value, answer.value.trim())
    if (res.data.error === 'wrong_answer') {
      errorMsg.value = '答案错误，请重试'
    } else {
      resetToken.value = res.data.reset_token
      step.value = 3
    }
  } catch {
    errorMsg.value = '网络错误，请重试'
  } finally {
    loading.value = false
  }
}

async function handleStep3() {
  if (!canSubmit.value) return
  loading.value = true
  errorMsg.value = ''
  successMsg.value = ''
  try {
    const res = await resetPassword(resetToken.value, newPassword.value)
    if (res.data.status === 'ok') {
      successMsg.value = '密码已重置成功！'
      setTimeout(() => router.push('/login'), 1500)
    }
  } catch (e) {
    if (e.response?.status === 400) {
      errorMsg.value = '重置链接已过期，请重新开始'
    } else {
      errorMsg.value = '重置失败，请重试'
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
.question-display {
  padding: 9px 12px;
  background: #f7f7f8;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  font-size: 13px;
  color: #1f1f1f;
}
.error-msg {
  font-size: 12px;
  color: #e03e3e;
  margin-bottom: 12px;
  padding: 6px 10px;
  background: #fef2f2;
  border-radius: 6px;
}
.success-msg {
  font-size: 12px;
  color: #1a8a3f;
  margin-bottom: 12px;
  padding: 6px 10px;
  background: #f0fdf4;
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
