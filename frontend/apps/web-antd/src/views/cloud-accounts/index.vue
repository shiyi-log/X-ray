<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { Plus, RefreshCw } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import {
  Alert, Button, Card, Form, Input, Modal, Select, Space, Table,
} from 'ant-design-vue';

import { resourcesApi, type Capability, type CloudAccount } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const DEFAULT_REGION = 'ap-southeast-1';
const FormItem = Form.Item;
const InputPassword = Input.Password;
const accountColumns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '平台', dataIndex: 'provider', key: 'provider' },
  { title: '外部账号', dataIndex: 'external_account_id', key: 'external_account_id' },
  { title: '凭据版本', dataIndex: 'credential_version', key: 'credential_version' },
  { title: '验证', dataIndex: 'last_validation_code', key: 'last_validation_code' },
  { title: '状态', dataIndex: 'enabled', key: 'enabled' },
  { title: '操作', key: 'actions' },
];
const capabilityColumns = [
  { title: '能力', dataIndex: 'name', key: 'name' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '说明', dataIndex: 'reason', key: 'reason' },
];
const providerOptions = [
  { label: 'AWS Lightsail', value: 'aws_lightsail' },
  { label: '阿里云 SWAS', value: 'aliyun_swas' },
];

const { data, loading, error, reload } = useResource(resourcesApi.cloudAccounts);
const createOpen = ref(false);
const saving = ref(false);
const formError = ref('');
const capabilityAccount = ref<CloudAccount | null>(null);
const capabilityRows = ref<Capability[]>([]);
const capabilityError = ref('');
const form = reactive({
  name: '',
  provider: 'aws_lightsail',
  region: DEFAULT_REGION,
  accessKey: '',
  secretKey: '',
});
const empty = computed(() => !data.value?.items.length);

async function createAccount() {
  if (saving.value) return;
  saving.value = true;
  formError.value = '';
  try {
    const credentials =
      form.provider === 'aws_lightsail'
        ? { access_key_id: form.accessKey, secret_access_key: form.secretKey }
        : { access_key_id: form.accessKey, access_key_secret: form.secretKey };
    await resourcesApi.createCloudAccount({
      name: form.name,
      provider: form.provider,
      region: form.region,
      credentials,
    });
    Object.assign(form, {
      name: '', provider: 'aws_lightsail', region: DEFAULT_REGION, accessKey: '', secretKey: '',
    });
    createOpen.value = false;
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '创建失败';
  } finally {
    saving.value = false;
    form.accessKey = '';
    form.secretKey = '';
  }
}

function resetCreateSecrets() {
  form.accessKey = '';
  form.secretKey = '';
  form.region = DEFAULT_REGION;
  formError.value = '';
}

async function showCapabilities(account: CloudAccount) {
  capabilityAccount.value = account;
  capabilityRows.value = [];
  capabilityError.value = '';
  try {
    capabilityRows.value = (await resourcesApi.capabilities(account.id)).items;
  } catch (caught) {
    capabilityError.value = caught instanceof Error ? caught.message : '能力加载失败';
  }
}
</script>

<template>
  <Page title="云账号" description="AWS Lightsail 与阿里云 SWAS">
    <template #title><h1 class="mb-2 text-lg font-semibold">云账号</h1></template>
    <template #extra>
      <Space>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button type="primary" @click="createOpen = true">
          <template #icon><Plus :size="16" /></template>
          添加账号
        </Button>
      </Space>
    </template>
    <Card>
      <PageState
        :loading="loading"
        :error="error"
        :empty="empty"
        empty-text="暂无云账号"
        @retry="reload"
      >
        <Table
          :columns="accountColumns"
          :data-source="data?.items || []"
          :pagination="false"
          :scroll="{ x: 'max-content' }"
          row-key="id"
        >
          <template #bodyCell="{ column, record }">
            <strong v-if="column.key === 'name'">{{ record.name }}</strong>
            <template v-else-if="column.key === 'provider'">
              {{ record.provider === 'aws_lightsail' ? 'AWS Lightsail' : '阿里云 SWAS' }}
            </template>
            <template v-else-if="column.key === 'credential_version'">v{{ record.credential_version }}</template>
            <StatusBadge v-else-if="column.key === 'last_validation_code'" :value="record.last_validation_code || 'UNVERIFIED'" />
            <StatusBadge v-else-if="column.key === 'enabled'" :value="record.enabled" />
            <Button v-else-if="column.key === 'actions'" type="link" @click="showCapabilities(record as CloudAccount)">能力</Button>
          </template>
        </Table>
      </PageState>
    </Card>
    <Modal
      v-model:open="createOpen"
      title="添加云账号"
      :footer="null"
      :mask-closable="!saving"
      :closable="!saving"
      :keyboard="!saving"
      :after-close="resetCreateSecrets"
      @cancel="resetCreateSecrets"
    >
      <Form :model="form" layout="vertical" @finish="createAccount">
        <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
        <FormItem label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
          <Input v-model:value="form.name" />
        </FormItem>
        <FormItem label="平台" name="provider">
          <Select v-model:value="form.provider" :options="providerOptions" />
        </FormItem>
        <FormItem label="区域" name="region">
          <Input v-model:value="form.region" placeholder="默认新加坡（ap-southeast-1），可留空" />
        </FormItem>
        <FormItem label="Access Key" name="accessKey" :rules="[{ required: true, message: '请输入 Access Key' }]">
          <Input v-model:value="form.accessKey" autocomplete="off" />
        </FormItem>
        <FormItem label="Secret Key" name="secretKey" :rules="[{ required: true, message: '请输入 Secret Key' }]">
          <InputPassword v-model:value="form.secretKey" autocomplete="new-password" />
        </FormItem>
        <Button type="primary" html-type="submit" :loading="saving" block>
          {{ saving ? '验证中' : '验证并保存' }}
        </Button>
      </Form>
    </Modal>
    <Modal
      :open="Boolean(capabilityAccount)"
      title="能力矩阵"
      :footer="null"
      @cancel="capabilityAccount = null"
    >
      <Alert v-if="capabilityError" :message="capabilityError" type="error" show-icon />
      <Table v-else :columns="capabilityColumns" :data-source="capabilityRows" :pagination="false" :scroll="{ x: 'max-content' }" row-key="name">
        <template #bodyCell="{ column, record }">
          <StatusBadge v-if="column.key === 'status'" :value="record.status" />
          <template v-else-if="column.key === 'reason'">{{ record.reason || '-' }}</template>
        </template>
      </Table>
    </Modal>
  </Page>
</template>
