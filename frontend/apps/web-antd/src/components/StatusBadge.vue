<script setup lang="ts">
import { computed } from 'vue';
import { Tag } from 'ant-design-vue';

const props = defineProps<{ value?: string | boolean | null }>();
const normalized = computed(() => String(props.value ?? 'UNKNOWN').toUpperCase());
const color = computed(() => {
  if (['READY', 'OPEN', 'ACTIVE', 'SUCCEEDED', 'SUPPORTED', 'OK', 'TRUE'].includes(normalized.value)) return 'success';
  if (['FAILED', 'REVOKED', 'UNSUPPORTED', 'REVOCATION_UNCONFIRMED', 'ISOLATION_UNCONFIRMED', 'FALSE'].includes(normalized.value)) return 'error';
  if (['RUNNING', 'PENDING', 'RETRY_PENDING', 'REVOKING', 'UNVERIFIED', 'MAINTENANCE', 'QUARANTINED'].includes(normalized.value)) return 'warning';
  return 'default';
});
</script>

<template><Tag class="m-0" :color="color">{{ normalized }}</Tag></template>
