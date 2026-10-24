<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { Plus, RefreshCw } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import {
  Alert, Button, Card, Form, Input, Modal, Select, Space, Table,
} from 'ant-design-vue';

import { resourcesApi, type CloudAccount, type NodePool } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const DEFAULT_REGION = 'ap-southeast-1';
const FormItem = Form.Item;
const columns = [
  { title: '节点', dataIndex: 'name', key: 'name' },
  { title: '平台/区域', key: 'provider' },
  { title: '云原始状态', dataIndex: 'raw_cloud_state', key: 'raw_cloud_state' },
  { title: '部署', dataIndex: 'provisioning_state', key: 'provisioning_state' },
  { title: '健康', dataIndex: 'health_state', key: 'health_state' },
  { title: '安全', dataIndex: 'security_state', key: 'security_state' },
  { title: 'Generation', key: 'generation' },
];

const router = useRouter();
const { data, loading, error, reload } = useResource(resourcesApi.nodes);
const open = ref(false);
const saving = ref(false);
const formError = ref('');
const pools = ref<NodePool[]>([]);
const accounts = ref<CloudAccount[]>([]);
const form = reactive({ pool_id: '', account_id: '', region: DEFAULT_REGION, plan_id: '', image_id: '' });
const empty = computed(() => !data.value?.items.length);
const poolOptions = computed(() => pools.value.map((item) => ({
  label: `${item.name}（可用 ${item.available}）`,
  value: item.id,
  disabled: !item.allow_create || item.available < 1,
})));
const accountOptions = computed(() => accounts.value.map((item) => ({
  label: item.name,
  value: item.id,
})));

async function openCreate() {
  open.value = true;
  formError.value = '';
  try {
    const [poolPage, accountPage] = await Promise.all([
      resourcesApi.nodePools(),
      resourcesApi.cloudAccounts(),
    ]);
    pools.value = poolPage.items;
    accounts.value = accountPage.items.filter((item) => item.enabled);
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '依赖数据加载失败';
  }
}

async function createNode() {
  if (saving.value) return;
  saving.value = true;
  formError.value = '';
  try {
    const result = await resourcesApi.createNode({ ...form }, crypto.randomUUID());
    open.value = false;
    await router.push(`/operations/${result.operation_id}`);
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '提交失败';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Page title="节点" description="云状态、服务状态与安全状态分开展示">
    <template #title><h1 class="mb-2 text-lg font-semibold">节点</h1></template>
    <template #extra>
      <Space>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button type="primary" @click="openCreate">
          <template #icon><Plus :size="16" /></template>
          创建节点
        </Button>
      </Space>
    </template>
    <Card>
      <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无节点" @retry="reload">
        <Table :columns="columns" :data-source="data?.items || []" :pagination="false" :scroll="{ x: 'max-content' }" row-key="id">
          <template #bodyCell="{ column, record }">
            <div v-if="column.key === 'name'">
              <strong>{{ record.name }}</strong>
              <div class="text-xs text-muted-foreground">{{ record.external_id || record.id }}</div>
            </div>
            <div v-else-if="column.key === 'provider'">
              {{ record.provider }}
              <div class="text-xs text-muted-foreground">{{ record.region }}</div>
            </div>
            <StatusBadge v-else-if="column.key === 'raw_cloud_state'" :value="record.raw_cloud_state || 'UNKNOWN'" />
            <StatusBadge v-else-if="column.key === 'provisioning_state'" :value="record.provisioning_state" />
            <StatusBadge v-else-if="column.key === 'health_state'" :value="record.health_state" />
            <StatusBadge v-else-if="column.key === 'security_state'" :value="record.security_state" />
            <template v-else-if="column.key === 'generation'">{{ record.applied_generation }} / {{ record.desired_generation }}</template>
          </template>
        </Table>
      </PageState>
    </Card>
    <Modal v-model:open="open" title="创建节点" :footer="null" :after-close="() => { form.region = DEFAULT_REGION; }">
      <Form :model="form" layout="vertical" @finish="createNode">
        <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
        <FormItem label="节点池" name="pool_id" :rules="[{ required: true, message: '请选择节点池' }]">
          <Select v-model:value="form.pool_id" :options="poolOptions" placeholder="请选择" />
        </FormItem>
        <FormItem label="云账号" name="account_id" :rules="[{ required: true, message: '请选择云账号' }]">
          <Select v-model:value="form.account_id" :options="accountOptions" placeholder="请选择" />
        </FormItem>
        <FormItem label="区域" name="region">
          <Input v-model:value="form.region" placeholder="默认新加坡（ap-southeast-1），可留空" />
        </FormItem>
        <FormItem label="套餐 ID" name="plan_id" :rules="[{ required: true, message: '请输入套餐 ID' }]">
          <Input v-model:value="form.plan_id" />
        </FormItem>
        <FormItem label="镜像 ID" name="image_id" :rules="[{ required: true, message: '请输入镜像 ID' }]">
          <Input v-model:value="form.image_id" />
        </FormItem>
        <Button type="primary" html-type="submit" :loading="saving" block>{{ saving ? '提交中' : '提交创建操作' }}</Button>
      </Form>
    </Modal>
  </Page>
</template>
