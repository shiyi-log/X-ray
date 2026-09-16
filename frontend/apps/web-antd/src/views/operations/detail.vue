<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { RefreshCw, RotateCcw, XCircle } from 'lucide-vue-next';

import { resourcesApi } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useOperation } from '@/composables/useOperation';

const route = useRoute();
const id = computed(() => String(route.params.id));
const { data, loading, error, reload } = useOperation(id.value);
const revocationStates = computed(() => data.value?.revocation_nodes || []);
const revocationVerified = computed(
  () =>
    revocationStates.value.length > 0 &&
    revocationStates.value.every((item) => item.status === 'VERIFIED_REVOKED'),
);
const revocationUnconfirmed = computed(
  () =>
    data.value?.kind === 'subscription.revoke' &&
    (!revocationVerified.value || data.value?.status === 'PARTIALLY_SUCCEEDED'),
);

async function cancel() {
  await resourcesApi.cancelOperation(id.value);
  await reload();
}

async function retry() {
  await resourcesApi.retryOperation(id.value);
  await reload();
}
</script>

<template>
  <PageHeader :title="data?.kind || '操作详情'" :subtitle="id">
    <template #actions>
      <button class="icon-button" title="刷新" aria-label="刷新" @click="reload"><RefreshCw :size="17" /></button>
      <button v-if="data?.can_cancel" class="secondary-command" @click="cancel"><XCircle :size="17" />取消</button>
      <button v-if="['PARTIALLY_SUCCEEDED', 'NEEDS_RECONCILIATION'].includes(data?.status || '')" class="command" @click="retry"><RotateCcw :size="17" />重试未完成项</button>
    </template>
  </PageHeader>
  <PageState :loading="loading" :error="error" @retry="reload">
    <section class="operation-summary">
      <div><span>ID</span><code data-testid="operation-id">{{ data?.id }}</code></div>
      <div><span>状态</span><StatusBadge data-testid="operation-state" :value="data?.status" /></div>
      <div><span>当前步骤</span><strong>{{ data?.current_step || '-' }}</strong></div>
      <div><span>错误</span><strong class="danger-text">{{ data?.error_code || '-' }}</strong></div>
    </section>
    <section v-if="data?.kind === 'subscription.revoke'" class="revocation-summary" aria-label="撤销结果">
      <div class="result-line success-line"><strong>链接已撤销</strong><span>旧订阅 Token 已永久进入 tombstone。</span></div>
      <div v-if="revocationVerified" class="result-line success-line"><strong>节点访问已验证失效</strong><span>每个目标凭据均有拒绝探测证据。</span></div>
      <div v-else-if="revocationUnconfirmed" class="result-line warning-line"><strong>节点访问撤销未确认</strong><span>系统保持失败关闭；不得视为全部旧凭据已失效。</span></div>
      <div v-for="item in revocationStates" :key="String(item.node_id)" class="node-result"><code>{{ item.node_id }}</code><StatusBadge :value="String(item.status)" /><span>{{ item.last_error_code || '-' }}</span></div>
    </section>
    <section class="timeline">
      <h2>执行步骤</h2>
      <PageState :empty="!data?.steps?.length" empty-text="尚无步骤记录">
        <ol><li v-for="step in data?.steps" :key="`${step.name}-${step.attempt}`"><span class="timeline-dot"></span><div><strong>{{ step.name }}</strong><small>{{ step.phase }} · 第 {{ step.attempt }} 次</small></div><StatusBadge :value="step.status" /></li></ol>
      </PageState>
    </section>
  </PageState>
</template>

<style scoped src="../styles/resource-page.css"></style>
<style scoped>
.operation-summary { display: grid; grid-template-columns: 2fr 1fr 1.5fr 1fr; margin-top: 18px; border: 1px solid var(--x-border); background: white; }
.operation-summary > div { min-height: 80px; display: flex; flex-direction: column; justify-content: center; gap: 6px; padding: 12px 15px; border-right: 1px solid var(--x-border); }
.operation-summary > div:last-child { border: 0; }
.operation-summary span { color: var(--x-text-muted); font-size: 11px; }
.operation-summary code { overflow: hidden; text-overflow: ellipsis; }
.timeline { margin-top: 18px; border: 1px solid var(--x-border); background: white; }
.timeline h2 { margin: 0; padding: 15px 17px; border-bottom: 1px solid var(--x-border); font-size: 14px; }
.timeline ol { margin: 0; padding: 0 18px; list-style: none; }
.timeline li { min-height: 64px; display: grid; grid-template-columns: 12px 1fr auto; align-items: center; gap: 12px; border-bottom: 1px solid var(--x-border); }
.timeline li:last-child { border: 0; }
.timeline-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--x-accent); }
.timeline small { display: block; margin-top: 3px; color: var(--x-text-muted); }
.danger-text { color: var(--x-danger); }
.revocation-summary { margin-top: 18px; border: 1px solid var(--x-border); background: white; }
.result-line { min-height: 56px; display: grid; grid-template-columns: 210px 1fr; align-items: center; gap: 12px; padding: 10px 15px; border-bottom: 1px solid var(--x-border); }
.result-line span { color: var(--x-text-muted); font-size: 12px; }
.success-line { border-left: 3px solid var(--x-success); }
.warning-line { color: #7b5100; border-left: 3px solid var(--x-warning); background: #fffaf0; }
.node-result { min-height: 48px; display: grid; grid-template-columns: minmax(180px, 1fr) auto minmax(100px, .7fr); align-items: center; gap: 12px; padding: 8px 15px; border-bottom: 1px solid var(--x-border); }
.node-result:last-child { border-bottom: 0; }
.node-result code { overflow: hidden; font-size: 11px; text-overflow: ellipsis; }
@media (max-width: 800px) { .operation-summary { grid-template-columns: 1fr 1fr; } .operation-summary > div:nth-child(2) { border-right: 0; } .operation-summary > div:nth-child(-n+2) { border-bottom: 1px solid var(--x-border); } }
@media (max-width: 560px) { .result-line { grid-template-columns: 1fr; gap: 3px; } .node-result { grid-template-columns: 1fr auto; } .node-result span { grid-column: 1 / -1; } }
</style>
