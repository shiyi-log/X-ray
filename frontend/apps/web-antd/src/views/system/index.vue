<script setup lang="ts">
import { computed, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { Alert, Button, Card, Descriptions, DescriptionsItem, Input, InputNumber, Space, Switch, Tag } from 'ant-design-vue';

import { regionLabel, resourcesApi, type NodePoolCreationTemplate } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import SecuritySettings from './SecuritySettings.vue';
import OnlineUpgrade from './OnlineUpgrade.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.system);
const savingNetworkSetting = ref(false);
const savingStatusSync = ref(false);
const savingPoolSync = ref(false);
const savingDailyRestart = ref(false);
const savingUsageSync = ref(false);
const statusSyncInterval = ref(60);
const poolSyncInterval = ref(15);
const poolTemplates = ref<NodePoolCreationTemplate[]>([]);
const templateRegion = ref('');
const templateCloudAccountId = ref('');
const templatePlanId = ref('');
const templateImageId = ref('');
const dailyRestartTime = ref('04:00');
const dailyRestartTimezone = ref('Asia/Shanghai');
const usageSyncInterval = ref(1);
const updateError = ref('');
watch(
  () => data.value?.node_status_sync?.interval_minutes,
  (value) => {
    if (typeof value === 'number') statusSyncInterval.value = value;
  },
  { immediate: true },
);
watch(
  () => data.value?.node_pool_sync,
  (value) => {
    if (!value) return;
    poolSyncInterval.value = value.interval_minutes;
    poolTemplates.value = value.creation_templates.map((template) => ({ ...template }));
  },
  { immediate: true },
);
watch(
  () => data.value?.node_daily_restart,
  (value) => {
    if (!value) return;
    dailyRestartTime.value = value.time;
    dailyRestartTimezone.value = value.timezone;
  },
  { immediate: true },
);
watch(
  () => data.value?.usage_sync?.interval_minutes,
  (value) => {
    if (typeof value === 'number') usageSyncInterval.value = value;
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

async function updateAutomation(
  patch: Parameters<typeof resourcesApi.updateSystem>[0],
  saving: typeof savingPoolSync,
  errorMessage: string,
): Promise<boolean> {
  if (saving.value || !data.value) return false;
  saving.value = true;
  updateError.value = '';
  try {
    data.value = await resourcesApi.updateSystem(patch);
    return true;
  } catch (caught) {
    updateError.value = caught instanceof Error ? caught.message : errorMessage;
    return false;
  } finally {
    saving.value = false;
  }
}

function handlePoolSyncChange(checked: unknown) {
  if (typeof checked === 'boolean') void updateAutomation(
    { node_pool_sync_enabled: checked },
    savingPoolSync,
    '地址池同步设置保存失败',
  );
}

function savePoolSyncInterval() {
  const value = Number(poolSyncInterval.value);
  if (!Number.isInteger(value) || value < 5 || value > 1440) {
    updateError.value = '地址池同步间隔必须为 5 到 1440 分钟';
    return;
  }
  void updateAutomation(
    { node_pool_sync_interval_minutes: value },
    savingPoolSync,
    '地址池同步设置保存失败',
  );
}

async function addPoolTemplate() {
  const template = {
    region: templateRegion.value.trim(),
    cloud_account_id: templateCloudAccountId.value.trim(),
    plan_id: templatePlanId.value.trim(),
    image_id: templateImageId.value.trim(),
  };
  if (Object.values(template).some((value) => !value)) {
    updateError.value = '创建模板的地区、云账号、套餐和镜像均不能为空';
    return;
  }
  const nextTemplates = [...poolTemplates.value, template];
  const saved = await updateAutomation(
    { node_pool_sync_creation_templates: nextTemplates },
    savingPoolSync,
    '地址池创建模板保存失败',
  );
  if (!saved) return;
  templateRegion.value = '';
  templateCloudAccountId.value = '';
  templatePlanId.value = '';
  templateImageId.value = '';
}

async function removePoolTemplate(index: number) {
  const nextTemplates = poolTemplates.value.filter((_template, itemIndex) => itemIndex !== index);
  await updateAutomation(
    { node_pool_sync_creation_templates: nextTemplates },
    savingPoolSync,
    '地址池创建模板保存失败',
  );
}

function handleDailyRestartChange(checked: unknown) {
  if (typeof checked === 'boolean') void updateAutomation(
    { node_daily_restart_enabled: checked },
    savingDailyRestart,
    '每日重启设置保存失败',
  );
}

function saveDailyRestart() {
  if (!/^\d{2}:\d{2}$/.test(dailyRestartTime.value)) {
    updateError.value = '每日重启时间必须使用 HH:MM 格式';
    return;
  }
  void updateAutomation(
    {
      node_daily_restart_time: dailyRestartTime.value,
      node_daily_restart_timezone: dailyRestartTimezone.value.trim(),
    },
    savingDailyRestart,
    '每日重启设置保存失败',
  );
}

function handleUsageSyncChange(checked: unknown) {
  if (typeof checked === 'boolean') void updateAutomation(
    { usage_sync_enabled: checked },
    savingUsageSync,
    '流量同步设置保存失败',
  );
}

function saveUsageSyncInterval() {
  const value = Number(usageSyncInterval.value);
  if (!Number.isInteger(value) || value < 1 || value > 1440) {
    updateError.value = '流量同步间隔必须为 1 到 1440 分钟';
    return;
  }
  void updateAutomation(
    { usage_sync_interval_minutes: value },
    savingUsageSync,
    '流量同步设置保存失败',
  );
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
          <DescriptionsItem label="地址池数量对齐">
            <Space wrap>
              <StatusBadge :value="data?.node_pool_sync?.enabled" />
              <Switch
                :checked="data?.node_pool_sync?.enabled"
                :loading="savingPoolSync"
                :disabled="loading || savingPoolSync || !data"
                aria-label="地址池数量对齐"
                @change="handlePoolSyncChange"
              />
              <span>重复时间</span>
              <InputNumber
                v-model:value="poolSyncInterval"
                :min="5"
                :max="1440"
                :precision="0"
                :disabled="loading || savingPoolSync || !data"
                aria-label="地址池同步间隔（分钟）"
                addon-after="分钟"
              />
              <Button :loading="savingPoolSync" :disabled="loading || !data" @click="savePoolSyncInterval">保存地址池间隔</Button>
            </Space>
            <div class="mt-2 flex flex-wrap gap-2">
              <Input v-model:value="templateRegion" aria-label="创建模板地区" placeholder="地区，例如 ap-southeast-1" />
              <Input v-model:value="templateCloudAccountId" aria-label="创建模板云账号 ID" placeholder="云账号 ID" />
              <Input v-model:value="templatePlanId" aria-label="创建模板套餐 ID" placeholder="套餐 ID" />
              <Input v-model:value="templateImageId" aria-label="创建模板镜像 ID" placeholder="镜像 ID" />
              <Button :loading="savingPoolSync" :disabled="loading || !data" @click="addPoolTemplate">添加创建模板</Button>
            </div>
            <div v-for="(template, index) in poolTemplates" :key="`${template.region}-${index}`" class="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <Tag>{{ regionLabel(template.region) }}</Tag>
              <span>账号：{{ template.cloud_account_id }}</span>
              <span>套餐：{{ template.plan_id }}</span>
              <span>镜像：{{ template.image_id }}</span>
              <Button type="link" danger :disabled="savingPoolSync" @click="removePoolTemplate(index)">删除</Button>
            </div>
            <div class="mt-2 text-xs text-muted-foreground">
              最近排程：{{ data?.node_pool_sync?.last_scheduled_at ? new Date(data.node_pool_sync.last_scheduled_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '尚未运行' }}；创建必须使用这里明确配置的云账号、套餐和镜像。
            </div>
          </DescriptionsItem>
          <DescriptionsItem label="每日服务器重启">
            <Space wrap>
              <StatusBadge :value="data?.node_daily_restart?.enabled" />
              <Switch
                :checked="data?.node_daily_restart?.enabled"
                :loading="savingDailyRestart"
                :disabled="loading || savingDailyRestart || !data"
                aria-label="每日服务器重启"
                @change="handleDailyRestartChange"
              />
              <Input v-model:value="dailyRestartTime" aria-label="每日重启时间" placeholder="HH:MM" />
              <Input v-model:value="dailyRestartTimezone" aria-label="每日重启时区" placeholder="Asia/Shanghai" />
              <Button :loading="savingDailyRestart" :disabled="loading || !data" @click="saveDailyRestart">保存重启计划</Button>
            </Space>
            <div class="mt-2 text-xs text-muted-foreground">每天按创建时间排序只提交一台；重启后必须重新读回 IP 和运行状态。</div>
          </DescriptionsItem>
          <DescriptionsItem label="流量与订阅用量同步">
            <Space wrap>
              <StatusBadge :value="data?.usage_sync?.enabled" />
              <Switch
                :checked="data?.usage_sync?.enabled"
                :loading="savingUsageSync"
                :disabled="loading || savingUsageSync || !data"
                aria-label="流量与订阅用量同步"
                @change="handleUsageSyncChange"
              />
              <InputNumber
                v-model:value="usageSyncInterval"
                :min="1"
                :max="1440"
                :precision="0"
                :disabled="loading || savingUsageSync || !data"
                aria-label="流量同步间隔（分钟）"
                addon-after="分钟"
              />
              <Button :loading="savingUsageSync" :disabled="loading || !data" @click="saveUsageSyncInterval">保存流量间隔</Button>
            </Space>
            <div class="mt-2 text-xs text-muted-foreground">只接受新鲜、可信的节点统计；订阅节点计数会同时核对 expected、assigned、ready 和 published。</div>
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
          type="warning"
          show-icon
          role="note"
          message="自动运维会提交云资源操作"
          description="启用地址池对齐或每日重启前请确认配额、资源归属和订阅影响；缩容按地区删除最早创建的服务器，后台仍会执行目标重验和云端读回。"
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
    <OnlineUpgrade class="mt-4" :current-version="data?.version" />
    <SecuritySettings class="mt-4" />
  </Page>
</template>
