<script setup lang="ts">
import { Alert, Button, Empty, Spin } from 'ant-design-vue';

defineProps<{ loading?: boolean; error?: string; empty?: boolean; emptyText?: string }>();
defineEmits<{ retry: [] }>();
</script>

<template>
  <div v-if="loading" class="flex min-h-48 items-center justify-center gap-3" role="status">
    <Spin /><span>正在加载</span>
  </div>
  <Alert v-else-if="error" :message="error" type="error" show-icon role="alert">
    <template #action>
      <Button size="small" aria-label="重试" @click="$emit('retry')">重试</Button>
    </template>
  </Alert>
  <Empty v-else-if="empty" class="py-10" :description="emptyText || '暂无数据'" />
  <slot v-else />
</template>
