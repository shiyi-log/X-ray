<script setup lang="ts">
import { computed, ref } from 'vue';
import { KeyRound, Plus, RefreshCw } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';
import { Alert, Button, Card, Form, Input, Modal, Space, Table } from 'ant-design-vue';

import { resourcesApi, type SecretDelivery as SecretDeliveryValue } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import SecretDelivery from '@/components/SecretDelivery.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.accessProfiles);
const open = ref(false);
const name = ref('');
const formError = ref('');
const actionError = ref('');
const issuingId = ref('');
const delivery = ref<SecretDeliveryValue | null>(null);
const empty = computed(() => !data.value?.items.length);
const columns = [
  { title: '名称', key: 'name', dataIndex: 'name' },
  { title: '状态', key: 'status', dataIndex: 'status' },
  { title: '活动凭据', key: 'credential_count', dataIndex: 'credential_count' },
  { title: '订阅', key: 'subscription_status', dataIndex: 'subscription_status' },
  { title: '发布冻结', key: 'publishing_frozen', dataIndex: 'publishing_frozen' },
  { title: '操作', key: 'actions' },
];

async function createProfile() {
  formError.value = '';
  try {
    await resourcesApi.createAccessProfile(name.value);
    name.value = '';
    open.value = false;
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '创建失败';
  }
}

async function issue(profileId: string) {
  actionError.value = '';
  issuingId.value = profileId;
  try {
    delivery.value = await resourcesApi.issueSubscription(profileId);
    await reload();
  } catch (caught) {
    actionError.value = caught instanceof Error ? caught.message : '签发失败';
  } finally {
    issuingId.value = '';
  }
}

function closeDelivery() {
  delivery.value = null;
}
</script>

<template>
  <Page title="访问配置" description="设备与用途身份">
    <template #title><h1 class="mb-2 text-lg font-semibold">访问配置</h1></template>
    <template #extra>
      <Space>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="17" /></template>
        </Button>
        <Button type="primary" @click="open = true">
          <template #icon><Plus :size="17" /></template>
          新建访问配置
        </Button>
      </Space>
    </template>
    <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无访问配置" @retry="reload">
      <Alert v-if="actionError" class="mb-4" type="error" show-icon :message="actionError" role="alert" />
      <Card :bordered="false">
        <Table :columns="columns" :data-source="data?.items || []" row-key="id" :pagination="false" :scroll="{ x: 'max-content' }">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <strong class="block font-medium">{{ record.name }}</strong>
              <small class="text-muted-foreground">{{ record.id }}</small>
            </template>
            <StatusBadge v-else-if="column.key === 'status'" :value="record.status" />
            <template v-else-if="column.key === 'credential_count'">{{ record.credential_count }}</template>
            <StatusBadge v-else-if="column.key === 'subscription_status'" :value="record.subscription_status || 'NOT_ISSUED'" />
            <StatusBadge v-else-if="column.key === 'publishing_frozen'" :value="record.publishing_frozen" />
            <template v-else-if="column.key === 'actions'">
              <Button v-if="!record.subscription_id && record.status === 'ACTIVE'" type="link" :disabled="issuingId === record.id" :loading="issuingId === record.id" @click="issue(record.id)">
                <template #icon><KeyRound :size="14" /></template>
                {{ issuingId === record.id ? '签发中' : '签发 Token' }}
              </Button>
              <span v-else class="text-muted-foreground">-</span>
            </template>
          </template>
        </Table>
      </Card>
    </PageState>
    <Modal v-model:open="open" title="新建访问配置" :footer="null">
      <Form layout="vertical" :model="{ name }" @finish="createProfile">
        <Alert v-if="formError" class="mb-4" type="error" show-icon :message="formError" role="alert" />
        <Form.Item label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
          <Input v-model:value="name" required />
        </Form.Item>
        <Button type="primary" html-type="submit">创建</Button>
      </Form>
    </Modal>
    <SecretDelivery :open="Boolean(delivery)" :delivery="delivery" @close="closeDelivery" />
  </Page>
</template>
