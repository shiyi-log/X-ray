<script setup lang="ts">
import { computed, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Alert, Card, Descriptions, DescriptionsItem, Space, Switch, Tag } from 'ant-design-vue';

import { resourcesApi } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.system);
const savingNetworkSetting = ref(false);
const updateError = ref('');
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
</script>

<template>
  <Page title="系统设置" description="系统信息与云身份校验设置">
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
        </Descriptions>
        <Alert
          class="mt-4"
          type="warning"
          show-icon
          role="note"
          message="此设置只控制云账号身份校验时的联网请求，不授予云资源写入权限。"
          description="启用后，后续新增、轮换或重新验证云账号凭据时可请求云厂商身份信息；资源创建、启停和删除仍须通过独立的云操作授权流程。"
        />
      </PageState>
    </Card>
  </Page>
</template>
