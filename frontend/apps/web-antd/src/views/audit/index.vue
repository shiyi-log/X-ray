<script setup lang="ts">
import { computed } from 'vue';
import { RefreshCw } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import { Button, Card, Table, Typography } from 'ant-design-vue';

import { resourcesApi } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';
import { auditActionLabel, targetTypeLabel } from '@/views/overview/presentation';

const { data, loading, error, reload } = useResource(resourcesApi.auditEvents);
const empty = computed(() => !data.value?.items.length);
const columns = [
  { title: '时间', key: 'created_at', width: 200 },
  { title: '动作', dataIndex: 'action', key: 'action' },
  { title: '目标', key: 'target', width: 280 },
  { title: '结果', key: 'result', width: 160 },
  { title: '请求 ID', dataIndex: 'request_id', key: 'request_id', width: 280 },
];
</script>

<template>
  <Page title="审计日志" description="追加记录，不包含秘密正文">
    <template #title>
      <h1 class="mb-2 text-lg font-semibold">审计日志</h1>
    </template>
    <template #extra>
      <Button title="刷新" aria-label="刷新" @click="reload">
        <template #icon><RefreshCw :size="16" /></template>
      </Button>
    </template>
    <Card :bordered="false">
      <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无审计记录" @retry="reload">
        <Table :columns="columns" :data-source="data?.items || []" :pagination="false" :scroll="{ x: 1000 }" row-key="id">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'created_at'">{{ new Date(record.created_at).toLocaleString('zh-CN') }}</template>
            <template v-else-if="column.key === 'action'">{{ auditActionLabel(record.action) }}</template>
            <template v-else-if="column.key === 'target'">
              {{ targetTypeLabel(record.target_type) }}
              <div><Typography.Text type="secondary">{{ record.target_id || '-' }}</Typography.Text></div>
            </template>
            <StatusBadge v-else-if="column.key === 'result'" :value="record.result" />
            <template v-else-if="column.key === 'request_id'">{{ record.request_id || '-' }}</template>
          </template>
        </Table>
      </PageState>
    </Card>
  </Page>
</template>
