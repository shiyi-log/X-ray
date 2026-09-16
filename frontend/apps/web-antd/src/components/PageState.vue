<script setup lang="ts">
import { AlertTriangle, Inbox, LoaderCircle, RefreshCw } from 'lucide-vue-next';

defineProps<{ loading?: boolean; error?: string; empty?: boolean; emptyText?: string }>();
defineEmits<{ retry: [] }>();
</script>

<template>
  <div v-if="loading" class="state-row" role="status">
    <LoaderCircle class="spin" :size="19" /><span>正在加载</span>
  </div>
  <div v-else-if="error" class="state-row error" role="alert">
    <AlertTriangle :size="19" /><span>{{ error }}</span>
    <button type="button" title="重试" aria-label="重试" @click="$emit('retry')">
      <RefreshCw :size="17" />
    </button>
  </div>
  <div v-else-if="empty" class="state-row empty">
    <Inbox :size="20" /><span>{{ emptyText || '暂无数据' }}</span>
  </div>
  <slot v-else />
</template>

<style scoped>
.state-row { min-height: 180px; display: flex; align-items: center; justify-content: center; gap: 9px; color: var(--x-text-muted); border-bottom: 1px solid var(--x-border); }
.state-row.error { min-height: 64px; justify-content: flex-start; padding: 14px 16px; color: var(--x-danger); background: #fff1f0; border: 1px solid #ffc9c4; }
.state-row.error button { width: 34px; height: 34px; display: grid; place-items: center; margin-left: auto; border: 1px solid #e5a6a0; border-radius: 5px; color: var(--x-danger); background: white; cursor: pointer; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
