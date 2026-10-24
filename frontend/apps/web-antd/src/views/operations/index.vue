<script setup lang="ts">
import { computed } from 'vue';
import { RefreshCw } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import { Button, Card, Table, Typography } from 'ant-design-vue';

import { resourcesApi } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.operations);
const empty = computed(() => !data.value?.items.length);
const columns = [
  { title: '操作', key: 'operation', width: 280 },
  { title: '目标', key: 'target', width: 280 },
  { title: '状态', key: 'status', width: 180 },
  { title: '当前步骤', dataIndex: 'current_step', key: 'current_step' },
  { title: '更新时间', key: 'updated_at', width: 200 },
];
</script>

<template>
  <Page title="操作中心" description="所有副作用操作的持久状态">
    <template #title>
      <h1 class="mb-2 text-lg font-semibold">操作中心</h1>
    </template>
    <template #extra>
      <Button title="刷新" aria-label="刷新" @click="reload">
        <template #icon><RefreshCw :size="16" /></template>
      </Button>
    </template>
    <Card :bordered="false">
      <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无操作" @retry="reload">
        <Table :columns="columns" :data-source="data?.items || []" :pagination="false" :scroll="{ x: 1000 }" row-key="id">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'operation'">
              <RouterLink :to="`/operations/${record.id}`">{{ record.kind }}</RouterLink>
              <div><Typography.Text type="secondary">{{ record.id }}</Typography.Text></div>
            </template>
            <template v-else-if="column.key === 'target'">
              {{ record.target_type }}
              <div><Typography.Text type="secondary">{{ record.target_id }}</Typography.Text></div>
            </template>
            <StatusBadge v-else-if="column.key === 'status'" :value="record.status" />
            <template v-else-if="column.key === 'current_step'">{{ record.current_step || '-' }}</template>
            <template v-else-if="column.key === 'updated_at'">
              {{ record.updated_at ? new Date(record.updated_at).toLocaleString('zh-CN') : '-' }}
            </template>
          </template>
        </Table>
      </PageState>
    </Card>
  </Page>
</template>
