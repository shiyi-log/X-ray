<script setup lang="ts">
import { computed, ref } from 'vue';
import { Plus, RefreshCw } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import { Button, Card, Space, Table } from 'ant-design-vue';

import {
  resourcesApi,
  regionLabel,
  type NodePool,
} from '@/api/resources';
import PageState from '@/components/PageState.vue';
import { useResource } from '@/composables/useResource';
import NodePoolAllocationEditor from './NodePoolAllocationEditor.vue';

const columns = [
  { title: 'IP', dataIndex: 'name', key: 'name' },
  { title: '地区', key: 'allocations' },
  { title: '允许创建', key: 'allow_create' },
];

const { data, loading, error, reload } = useResource(resourcesApi.nodePools);
const open = ref(false);
const empty = computed(() => !data.value?.items.length);
const pool = computed(() => data.value?.items[0] ?? null);

function openEditor() {
  open.value = true;
}

function regionSummary(item: NodePool) {
  const regions = item.allocations?.map((allocation) => allocation.region) ?? item.regions;
  return regions?.length ? regions.map(regionLabel).join('、') : regionLabel(item.region || '未配置');
}

</script>

<template>
  <Page title="地区分配" description="管理服务器创建地区额度">
    <template #title><h1 class="mb-2 text-lg font-semibold">地区分配</h1></template>
    <template #extra>
      <Space>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button type="primary" @click="openEditor">
          <template #icon><Plus :size="16" /></template>
          地区分配
        </Button>
      </Space>
    </template>
    <Card>
      <PageState
        :loading="loading"
        :error="error"
        :empty="empty"
        empty-text="暂无地区配置"
        @retry="reload"
      >
        <Table :columns="columns" :data-source="data?.items || []" :pagination="false" :scroll="{ x: 'max-content' }" row-key="id">
          <template #bodyCell="{ column, record }">
            <div v-if="column.key === 'name'">
              <strong>{{ record.name }}</strong>
              <div class="text-xs text-muted-foreground">{{ record.id }}</div>
            </div>
            <div v-else-if="column.key === 'allocations'">{{ regionSummary(record as NodePool) }}</div>
            <span v-else-if="column.key === 'allow_create'">
              {{ (record as NodePool).allow_create ?? true ? '允许' : '已关闭' }}
            </span>
          </template>
        </Table>
      </PageState>
    </Card>
    <NodePoolAllocationEditor v-model:open="open" :pool="pool" @saved="reload" />
  </Page>
</template>
