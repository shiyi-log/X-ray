<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{ value?: string | boolean | null }>();
const normalized = computed(() => String(props.value ?? 'UNKNOWN').toUpperCase());
const tone = computed(() => {
  if (['READY', 'OPEN', 'ACTIVE', 'SUCCEEDED', 'SUPPORTED', 'OK', 'TRUE'].includes(normalized.value)) return 'success';
  if (['FAILED', 'REVOKED', 'UNSUPPORTED', 'REVOCATION_UNCONFIRMED', 'ISOLATION_UNCONFIRMED', 'FALSE'].includes(normalized.value)) return 'danger';
  if (['RUNNING', 'PENDING', 'RETRY_PENDING', 'REVOKING', 'UNVERIFIED', 'MAINTENANCE', 'QUARANTINED'].includes(normalized.value)) return 'warning';
  return 'neutral';
});
</script>

<template><span class="status" :class="tone">{{ normalized }}</span></template>

<style scoped>
.status { display: inline-flex; align-items: center; min-height: 24px; padding: 2px 8px; border: 1px solid var(--x-border); border-radius: 4px; color: #52606c; background: #f7f9fa; font: 650 11px/1.2 var(--x-font); white-space: nowrap; }
.status.success { color: #24653b; border-color: #b7d9c2; background: #eef8f1; }
.status.warning { color: #8a5200; border-color: #ecd19c; background: #fff8e8; }
.status.danger { color: #9d2117; border-color: #efb3ae; background: #fff1f0; }
</style>
