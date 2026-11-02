<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { Alert, Button, Card, Descriptions, DescriptionsItem, InputNumber, Space, Switch, Tag } from 'ant-design-vue';

import { resourcesApi } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.system);
const savingNetworkSetting = ref(false);
const savingStatusSync = ref(false);
const statusSyncInterval = ref(60);
const updateError = ref('');
watch(
  () => data.value?.node_status_sync?.interval_minutes,
  (value) => {
    if (typeof value === 'number') statusSyncInterval.value = value;
  },
  { immediate: true },
);
const networkSettingSource = computed(() => {
  switch (data.value?.provider_identity_network?.source) {
    case 'DATABASE': return '数据库设置';
    case 'ENVIRONMENT': return '环境变量默认值';
    default: return '未知';
  }
});

async function updateNetworkSetting(enabled: boolean) {
  if (savingNetworkSetting.value || !data.value) return;
  savingNetworkSetting.value = true;
  updateError.value = '';
  try {
    data.value = await resourcesApi.updateSystem({
      provider_identity_network_enabled: enabled,
    });
  } catch (caught) {
    updateError.value = caught instanceof Error ? caught.message : '设置保存失败';
  } finally {
    savingNetworkSetting.value = false;
  }
}

function handleNetworkSettingChange(checked: unknown) {
  if (typeof checked === 'boolean') void updateNetworkSetting(checked);
}

async function updateStatusSync(patch: { node_status_sync_enabled?: boolean; node_status_sync_interval_minutes?: number }) {
  if (savingStatusSync.value || !data.value) return;
  savingStatusSync.value = true;
  updateError.value = '';
  try {
    data.value = await resourcesApi.updateSystem(patch);
    statusSyncInterval.value = data.value.node_status_sync.interval_minutes;
  } catch (caught) {
    updateError.value = caught instanceof Error ? caught.message : '状态同步设置保存失败';
  } finally {
    savingStatusSync.value = false;
  }
}

function handleStatusSyncChange(checked: unknown) {
  if (typeof checked === 'boolean') void updateStatusSync({ node_status_sync_enabled: checked });
}

function saveStatusSyncInterval() {
  const value = Number(statusSyncInterval.value);
  if (!Number.isInteger(value) || value < 5 || value > 1440) {
    updateError.value = '同步间隔必须为 5 到 1440 分钟';
    return;
  }
  void updateStatusSync({ node_status_sync_interval_minutes: value });
}
</script>

<template>
  <Page title="系统设置" description="系统信息与运行设置">
    <template #title>
      <h1 class="mb-2 text-lg font-semibold">系统设置</h1>
    </template>
    <Card :bordered="false">
      <PageState :loading="loading" :error="error" @retry="reload">
        <Alert
          v-if="updateError"
          class="mb-4"
          type="error"
          show-icon
          role="alert"
          :message="updateError"
        />
        <Descriptions bordered :column="1">
          <DescriptionsItem label="版本">{{ data?.version }}</DescriptionsItem>
          <DescriptionsItem label="环境">{{ data?.environment }}</DescriptionsItem>
          <DescriptionsItem label="调试模式"><StatusBadge :value="data?.debug" /></DescriptionsItem>
          <DescriptionsItem label="管理 Host allowlist">
            <Space wrap>
              <Tag v-for="item in data?.allowed_hosts" :key="item">{{ item }}</Tag>
              <span v-if="!data?.allowed_hosts?.length">未配置</span>
            </Space>
          </DescriptionsItem>
          <DescriptionsItem label="CSRF 可信来源">
            <Space wrap>
              <Tag v-for="item in data?.csrf_trusted_origins" :key="item">{{ item }}</Tag>
              <span v-if="!data?.csrf_trusted_origins?.length">未配置</span>
            </Space>
          </DescriptionsItem>
          <DescriptionsItem label="云身份校验联网">
            <Space wrap>
              <StatusBadge :value="data?.provider_identity_network?.enabled" />
              <span>来源：{{ networkSettingSource }}</span>
              <Switch
                :checked="data?.provider_identity_network?.enabled"
                :loading="savingNetworkSetting"
                :disabled="loading || savingNetworkSetting || !data"
                aria-label="云身份校验联网"
                @change="handleNetworkSettingChange"
              />
            </Space>
          </DescriptionsItem>
          <DescriptionsItem label="服务器状态同步">
            <Space wrap>
              <StatusBadge :value="data?.node_status_sync?.enabled" />
              <Switch
                :checked="data?.node_status_sync?.enabled"
                :loading="savingStatusSync"
                :disabled="loading || savingStatusSync || !data"
                aria-label="服务器状态同步"
                @change="handleStatusSyncChange"
              />
              <span>重复时间</span>
              <InputNumber
                v-model:value="statusSyncInterval"
                :min="5"
                :max="1440"
                :precision="0"
                :disabled="loading || savingStatusSync || !data"
                aria-label="同步重复时间（分钟）"
                addon-after="分钟"
              />
              <Button :loading="savingStatusSync" :disabled="loading || !data" @click="saveStatusSyncInterval">保存间隔</Button>
            </Space>
            <div class="mt-2 text-xs text-muted-foreground">
              最近排程：{{ data?.node_status_sync?.last_scheduled_at ? new Date(data.node_status_sync.last_scheduled_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '尚未运行' }}
            </div>
          </DescriptionsItem>
        </Descriptions>
        <Alert
          class="mt-4"
          type="warning"
          show-icon
          role="note"
          message="此设置只控制云账号身份校验时的联网请求，不授予云资源写入权限。"
          description="启用后，后续新增、轮换或重新验证云账号凭据时可请求云厂商身份信息；资源创建、启停和删除仍须通过独立的云操作授权流程。"
        />
        <Alert
          class="mt-3"
          type="info"
          show-icon
          role="note"
          message="状态同步只读取云端服务器状态，不会创建、启停或删除资源。"
          description="任务由后台调度器按分钟检查，到达重复时间后提交状态更新操作；已有更新操作时会跳过该服务器。"
        />
      </PageState>
    </Card>
  </Page>
</template>
