<script setup lang="ts">
import { computed } from 'vue';
import { Tag } from 'ant-design-vue';

const props = defineProps<{ value?: string | boolean | null }>();
const normalized = computed(() => String(props.value ?? 'UNKNOWN').toUpperCase());
const statusLabels: Record<string, string> = {
  UNKNOWN: '未知',
  PENDING: '待处理',
  RUNNING: '运行中',
  READY: '就绪',
  OPEN: '开放',
  ACTIVE: '活跃',
  NORMAL: '正常',
  SUCCEEDED: '成功',
  SUPPORTED: '支持',
  OK: '正常',
  TRUE: '是',
  FAILED: '失败',
  REVOKED: '已撤销',
  UNSUPPORTED: '不支持',
  REVOCATION_UNCONFIRMED: '撤销未确认',
  ISOLATION_UNCONFIRMED: '隔离未确认',
  FALSE: '否',
  RETRY_PENDING: '等待重试',
  CANCELLING: '取消中',
  CANCELLED: '已取消',
  REVOKING: '撤销中',
  UNVERIFIED: '未验证',
  MAINTENANCE: '维护中',
  QUARANTINED: '已隔离',
  NEEDS_RECONCILIATION: '需要协调',
  PARTIALLY_SUCCEEDED: '部分成功',
  RESERVED: '已预留',
  PROVISIONED: '已配置',
  DELETED: '已删除',
  STOPPED: '已停止',
  PRESENT: '存在',
  REQUESTED: '已请求',
  APPLYING: '应用中',
  CONFIG_APPLIED: '配置已应用',
  SERVICE_RESTARTED: '服务已重启',
  VERIFIED_REVOKED: '已验证撤销',
  NOT_ISSUED: '未签发',
  EXPIRED: '已过期',
  CANDIDATE: '候选',
  APPROVED: '已批准',
  REJECTED: '已拒绝',
  SUPERSEDED: '已替代',
  RECONCILED: '已协调',
  RECONCILIATION: '协调中',
};
const label = computed(() => statusLabels[normalized.value] ?? normalized.value);
const color = computed(() => {
  if (['READY', 'OPEN', 'ACTIVE', 'NORMAL', 'SUCCEEDED', 'SUPPORTED', 'OK', 'TRUE'].includes(normalized.value)) return 'success';
  if (['FAILED', 'REVOKED', 'UNSUPPORTED', 'REVOCATION_UNCONFIRMED', 'ISOLATION_UNCONFIRMED', 'FALSE'].includes(normalized.value)) return 'error';
  if (['RUNNING', 'PENDING', 'RETRY_PENDING', 'REVOKING', 'UNVERIFIED', 'MAINTENANCE', 'QUARANTINED'].includes(normalized.value)) return 'warning';
  return 'default';
});
</script>

<template><Tag class="m-0" :color="color">{{ label }}</Tag></template>
