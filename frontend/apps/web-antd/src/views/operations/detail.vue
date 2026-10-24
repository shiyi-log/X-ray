<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { RefreshCw, RotateCcw, XCircle } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Button,
  Card,
  Descriptions,
  DescriptionsItem,
  Space,
  Table,
  Timeline,
  TimelineItem,
  Typography,
} from 'ant-design-vue';

import { resourcesApi } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useOperation } from '@/composables/useOperation';

const route = useRoute();
const id = computed(() => String(route.params.id));
const { data, loading, error, reload } = useOperation(id.value);
const revocationStates = computed(() => [...(data.value?.revocation_nodes || [])]);
const revocationColumns = [
  { title: '节点', dataIndex: 'node_id', key: 'node_id' },
  { title: '撤销状态', key: 'status', width: 220 },
  { title: '错误', key: 'last_error_code' },
];
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
  <Page :title="data?.kind || '操作详情'" :description="id">
    <template #title>
      <h1 class="mb-2 text-lg font-semibold">{{ data?.kind || '操作详情' }}</h1>
    </template>
    <template #extra>
      <Space wrap>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button v-if="data?.can_cancel" @click="cancel">
          <template #icon><XCircle :size="16" /></template>
          取消
        </Button>
        <Button v-if="['PARTIALLY_SUCCEEDED', 'NEEDS_RECONCILIATION'].includes(data?.status || '')" type="primary" @click="retry">
          <template #icon><RotateCcw :size="16" /></template>
          重试未完成项
        </Button>
      </Space>
    </template>
    <PageState :loading="loading" :error="error" @retry="reload">
      <Space direction="vertical" size="middle" class="w-full">
        <Card :bordered="false">
          <Descriptions bordered :column="{ xs: 1, md: 2 }">
            <DescriptionsItem label="ID"><code data-testid="operation-id">{{ data?.id }}</code></DescriptionsItem>
            <DescriptionsItem label="状态"><StatusBadge data-testid="operation-state" :value="data?.status" /></DescriptionsItem>
            <DescriptionsItem label="当前步骤">{{ data?.current_step || '-' }}</DescriptionsItem>
            <DescriptionsItem label="错误"><Typography.Text :type="data?.error_code ? 'danger' : undefined">{{ data?.error_code || '-' }}</Typography.Text></DescriptionsItem>
          </Descriptions>
        </Card>
        <Card v-if="data?.kind === 'subscription.revoke'" title="撤销结果" :bordered="false" aria-label="撤销结果">
          <Space direction="vertical" size="middle" class="w-full">
            <Alert type="success" show-icon message="链接已撤销" description="旧订阅 Token 已永久进入 tombstone。" />
            <Alert v-if="revocationVerified" type="success" show-icon message="节点访问已验证失效" description="每个目标凭据均有拒绝探测证据。" />
            <Alert v-else-if="revocationUnconfirmed" type="warning" show-icon message="节点访问撤销未确认" description="系统保持失败关闭；不得视为全部旧凭据已失效。" />
            <Table v-if="revocationStates.length" :columns="revocationColumns" :data-source="revocationStates" :pagination="false" :scroll="{ x: 640 }" row-key="node_id" size="small">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'node_id'">{{ record.node_id }}</template>
                <StatusBadge v-else-if="column.key === 'status'" :value="String(record.status)" />
                <template v-else-if="column.key === 'last_error_code'">{{ record.last_error_code || '-' }}</template>
              </template>
            </Table>
          </Space>
        </Card>
        <Card title="执行步骤" :bordered="false">
          <PageState :empty="!data?.steps?.length" empty-text="尚无步骤记录">
            <Timeline>
              <TimelineItem v-for="step in data?.steps" :key="`${step.name}-${step.attempt}`">
                <Space direction="vertical" size="small">
                  <Space><Typography.Text strong>{{ step.name }}</Typography.Text><StatusBadge :value="step.status" /></Space>
                  <Typography.Text type="secondary">{{ step.phase }} · 第 {{ step.attempt }} 次</Typography.Text>
                </Space>
              </TimelineItem>
            </Timeline>
          </PageState>
        </Card>
      </Space>
    </PageState>
  </Page>
</template>
