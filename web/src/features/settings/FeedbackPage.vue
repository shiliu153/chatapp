<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import { parseApiError } from '@/api/error'
import { submitFeedback, type FeedbackType } from '@/api/settings'

const router = useRouter()
const TYPES: { value: FeedbackType; label: string }[] = [
  { value: 'feature', label: '功能建议' },
  { value: 'bug', label: '问题反馈' },
  { value: 'account', label: '账号问题' },
  { value: 'other', label: '其他' },
]

const type = ref<FeedbackType>('feature')
const content = ref('')
const contact = ref('')
const submitting = ref(false)
const error = ref('')
const submitted = ref(false)

const canSubmit = computed(
  () => !submitting.value && content.value.trim().length >= 10,
)

async function onSubmit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    await submitFeedback({
      type: type.value,
      content: content.value.trim(),
      ...(contact.value.trim() ? { contact: contact.value.trim() } : {}),
    })
    submitted.value = true
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section v-if="submitted" class="feedback feedback--done">
    <span class="feedback__check" aria-hidden="true">✓</span>
    <h1 class="feedback__done-title">已收到你的反馈</h1>
    <p class="feedback__done-desc">我们会认真看每一条建议,感谢你帮助心跳变得更好。</p>
    <AppButton block size="lg" @click="router.push({ name: 'settings' })">返回设置</AppButton>
  </section>

  <section v-else class="feedback">
    <header class="feedback__header">
      <RouterLink class="feedback__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="feedback__title">意见反馈</h1>
    </header>

    <div class="feedback__types">
      <button
        v-for="item in TYPES"
        :key="item.value"
        type="button"
        class="feedback__type"
        :class="{ 'feedback__type--active': type === item.value }"
        @click="type = item.value"
      >
        {{ item.label }}
      </button>
    </div>

    <label class="feedback__label">反馈内容</label>
    <textarea
      v-model="content"
      class="feedback__content"
      maxlength="500"
      rows="6"
      placeholder="说说遇到了什么,或希望我们做什么(至少 10 字)"
    />
    <span class="feedback__count">{{ content.length }}/500</span>

    <label class="feedback__label">联系方式(选填)</label>
    <div class="feedback__contact">
      <AppInput
        v-model="contact"
        :maxlength="64"
        placeholder="手机号 / 邮箱 / 微信,方便我们回复你"
      />
    </div>

    <p v-if="error" class="feedback__error">{{ error }}</p>

    <AppButton
      class="feedback__submit"
      block
      size="lg"
      :disabled="!canSubmit"
      :loading="submitting"
      @click="onSubmit"
    >
      提交反馈
    </AppButton>
  </section>
</template>

<style scoped>
.feedback {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.feedback--done {
  align-items: center;
  gap: var(--space-lg);
  padding-top: var(--space-xxl);
  text-align: center;
}
.feedback__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.feedback__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.feedback__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.feedback__types {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-sm);
}
.feedback__type {
  height: 44px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  color: var(--color-text1);
  font-size: var(--text-body);
  cursor: pointer;
}
.feedback__type--active {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
.feedback__label {
  color: var(--color-text2);
  font-size: var(--text-caption);
}
.feedback__content {
  width: 100%;
  padding: var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  color: var(--color-text1);
  font-family: var(--font-latin);
  font-size: var(--text-body);
  line-height: 1.6;
  resize: vertical;
}
.feedback__content:focus {
  border-color: var(--color-brand);
  outline: none;
  box-shadow: var(--focus-glow);
}
.feedback__count {
  align-self: flex-end;
  color: var(--color-text3);
  font-size: var(--text-micro);
}
.feedback__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-caption);
}
.feedback__check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: var(--radius-full);
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: 28px;
}
.feedback__done-title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.feedback__done-desc {
  margin: 0;
  color: var(--color-text2);
  font-size: var(--text-body);
  line-height: 1.6;
}
</style>
