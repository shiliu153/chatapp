<script setup lang="ts">
import { ref } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppInput from '@/components/AppInput.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'

const text = ref('')
const phone = ref('13800000001')
</script>

<template>
  <main class="dev">
    <h1 class="dev__h1">心跳组件目检</h1>

    <AppCard padding="lg">
      <h2 class="dev__h2">按钮</h2>
      <div class="dev__row">
        <AppButton>主要</AppButton>
        <AppButton variant="ghost">次要</AppButton>
        <AppButton variant="danger">危险</AppButton>
        <AppButton loading>加载中</AppButton>
        <AppButton disabled>禁用</AppButton>
      </div>
      <AppButton block size="lg">通栏大按钮</AppButton>
    </AppCard>

    <AppCard padding="lg">
      <h2 class="dev__h2">输入</h2>
      <div class="dev__col">
        <AppInput v-model="text" placeholder="说点什么" />
        <AppInput v-model="phone" error="验证码错误,请重试" />
        <AppInput :model-value="''" disabled placeholder="禁用态" />
      </div>
    </AppCard>

    <AppCard padding="lg">
      <h2 class="dev__h2">头像 / 角标 / 骨架</h2>
      <div class="dev__row">
        <AppAvatar name="小雨" :size="48" />
        <AppAvatar name="A" :size="40" />
        <AppAvatar :size="40" />
        <AppBadge :count="3" />
        <AppBadge :count="120" />
      </div>
      <div class="dev__col">
        <AppSkeleton height="20px" />
        <AppSkeleton width="60%" height="14px" />
      </div>
    </AppCard>

    <AppCard padding="lg">
      <h2 class="dev__h2">空态 / 错误态</h2>
      <AppEmpty title="还没有人给你点赞" description="去广场发条动态吧" />
      <AppErrorView message="网络开小差了" @retry="() => {}" />
    </AppCard>
  </main>
</template>

<style scoped>
.dev {
  display: flex;
  flex-direction: column;
  gap: var(--space-card-gap);
  max-width: 900px;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.dev__h1 {
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
  margin: 0;
}
.dev__h2 {
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
  margin: 0 0 var(--space-md);
}
.dev__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-md);
}
.dev__col {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  margin-top: var(--space-md);
}
</style>
