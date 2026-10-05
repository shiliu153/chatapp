<script setup lang="ts">
// Task 3.4 会替换为「可拖拽侧栏 + 内容区」的正式版;这里先保证路由可解析。
</script>

<template>
  <div class="shell">
    <main class="shell__content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.shell__content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}
</style>
