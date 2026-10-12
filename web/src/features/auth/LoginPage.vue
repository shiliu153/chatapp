<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import { useSessionStore } from '@/stores/session'
import FormCard from './FormCard.vue'

const PHONE_RE = /^\d{11}$/

const router = useRouter()
const session = useSessionStore()

const phone = ref('')
const code = ref('')
const error = ref('')
const sending = ref(false)
const submitting = ref(false)
const countdown = ref(0)
let timer: number | undefined

const canSend = computed(() => countdown.value === 0 && !sending.value)

function startCountdown(seconds: number) {
  countdown.value = seconds
  window.clearInterval(timer)
  timer = window.setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) window.clearInterval(timer)
  }, 1000)
}

onUnmounted(() => window.clearInterval(timer))

async function onSend() {
  error.value = ''
  if (!PHONE_RE.test(phone.value)) {
    error.value = '请输入 11 位手机号'
    return
  }
  sending.value = true
  try {
    await session.sendCode(phone.value)
    startCountdown(60)
  } catch (e) {
    const apiError = parseApiError(e)
    error.value = apiError.message
    // 42901:后端带 Retry-After,按它倒计时,而不是硬编码 60 秒
    if (apiError.isThrottled && apiError.retryAfter) startCountdown(apiError.retryAfter)
  } finally {
    sending.value = false
  }
}

async function onSubmit() {
  error.value = ''
  if (!PHONE_RE.test(phone.value)) {
    error.value = '请输入 11 位手机号'
    return
  }
  if (code.value.length !== 6) {
    error.value = '请输入 6 位验证码'
    return
  }
  submitting.value = true
  try {
    const { isNewUser } = await session.verify(phone.value, code.value)
    // 新号先去完善资料(与 App 一致):资料不全会永远进不了别人的候选卡
    await router.push(isNewUser ? { name: 'onboarding' } : { name: 'home' })
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <FormCard title="心跳" description="手机号登录,未注册将自动创建账号">
    <div class="login__field">
      <AppInput
        v-model="phone"
        type="tel"
        placeholder="手机号"
        :maxlength="11"
        :error="error"
        @enter="onSubmit"
      />
      <div class="login__code-row">
        <AppInput
          v-model="code"
          inputmode="numeric"
          placeholder="6 位验证码"
          :maxlength="6"
        />
        <AppButton
          class="login__send"
          variant="ghost"
          :disabled="!canSend"
          :loading="sending"
          @click="onSend"
        >
          {{ countdown > 0 ? `${countdown} 秒后重发` : '获取验证码' }}
        </AppButton>
      </div>
    </div>
    <AppButton
      class="login__submit"
      block
      size="lg"
      :loading="submitting"
      @click="onSubmit"
    >
      登录
    </AppButton>
  </FormCard>
</template>

<style scoped>
.login__field {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}
.login__code-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
}
.login__send {
  flex: none;
  white-space: nowrap;
}
</style>
