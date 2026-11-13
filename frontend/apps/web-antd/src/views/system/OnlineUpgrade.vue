<script setup lang="ts">
import { computed, onScopeDispose, ref } from 'vue';

import { Alert, Button, Card, Modal, Space, Tag } from 'ant-design-vue';

import { ApiError } from '@/api/request';
import { resourcesApi, type SystemUpgradeInfo, type SystemUpgradeJob } from '@/api/resources';

defineProps<{ currentVersion?: string }>();

const open = ref(false);
const checking = ref(false);
const submitting = ref(false);
const info = ref<SystemUpgradeInfo | null>(null);
const selectedVersion = ref('');
const job = ref<SystemUpgradeJob | null>(null);
const error = ref('');
const reconnecting = ref(false);
const uncertainSubmission = ref(false);
let requestKey = '';
let requestVersion = '';
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;

const running = computed(() => Boolean(job.value && !['SUCCEEDED', 'FAILED'].includes(job.value.status)));
const selectedRelease = computed(() => info.value?.candidates.find((item) => item.version === selectedVersion.value));
const canSubmit = computed(() => Boolean(info.value?.available && selectedRelease.value && !checking.value && !submitting.value && !running.value));
const phaseLabel = computed(() => {
  if (!job.value) return '';
  if (job.value.status === 'SUCCEEDED') return '升级成功';
  if (job.value.status === 'FAILED') return '升级失败';
  if (job.value.status === 'QUEUED') return '等待执行';
  const labels: Record<string, string> = {
    BACKUP: '正在备份',
    PREFLIGHT: '正在检查升级条件',
    DOWNLOAD: '正在准备版本',
    DRAIN: '正在等待后台任务结束',
    MIGRATE: '正在更新数据库',
    DEPLOY: '正在切换服务',
    VERIFY: '正在验证服务',
    COMPLETE: '正在确认升级结果',
  };
  return labels[job.value.phase] || '正在升级';
});

function clearPoll() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = undefined;
}

function schedulePoll() {
  clearPoll();
  if (disposed || (!running.value && !uncertainSubmission.value)) return;
  pollTimer = setTimeout(() => { void checkUpdates(true); }, 3000);
}

async function checkUpdates(background = false) {
  if (checking.value || disposed) return;
  checking.value = true;
  if (!background) error.value = '';
  try {
    const result = await resourcesApi.systemUpgrade();
    if (disposed) return;
    info.value = result;
    reconnecting.value = false;
    if (!result.candidates.some((item) => item.version === selectedVersion.value)) {
      selectedVersion.value = result.candidates[0]?.version || '';
    }
    const trackingId = requestKey || job.value?.id;
    const confirmedJob = trackingId
      ? result.jobs.find((item) => item.id === trackingId)
      : result.jobs.find((item) => !['SUCCEEDED', 'FAILED'].includes(item.status)) || result.jobs[0];
    if (confirmedJob) {
      job.value = confirmedJob;
      uncertainSubmission.value = false;
    }
  } catch {
    if (disposed) return;
    if (running.value || uncertainSubmission.value) reconnecting.value = true;
    else error.value = '无法检查更新，请稍后重试。';
  } finally {
    checking.value = false;
    schedulePoll();
  }
}

async function showUpgrade() {
  open.value = true;
  await checkUpdates();
}

async function startUpgrade() {
  if (!canSubmit.value) return;
  error.value = '';
  reconnecting.value = false;
  if (!requestKey || requestVersion !== selectedVersion.value || (job.value && !running.value && !uncertainSubmission.value)) {
    requestKey = crypto.randomUUID();
    requestVersion = selectedVersion.value;
  }
  submitting.value = true;
  try {
    const accepted = await resourcesApi.startSystemUpgrade({
      version: selectedVersion.value,
      confirmation: '确认在线升级',
    }, requestKey);
    if (disposed) return;
    job.value = accepted;
    uncertainSubmission.value = false;
  } catch (caught) {
    if (disposed) return;
    if (caught instanceof ApiError && caught.code === 'STEP_UP_REQUIRED') {
      error.value = '请先在本页“账号安全”中重新验证身份，再返回确认升级。';
    } else if (caught instanceof ApiError && caught.status < 500) {
      error.value = '升级请求未被接受，请检查更新后重试。';
    } else {
      uncertainSubmission.value = true;
      error.value = '升级请求尚未确认，正在重新连接；再次确认会核对同一请求。';
    }
  } finally {
    submitting.value = false;
    schedulePoll();
  }
}

onScopeDispose(() => {
  disposed = true;
  clearPoll();
});
</script>

<template>
  <Card title="版本更新" :bordered="false">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p>当前版本 <strong>{{ info?.current_version || currentVersion || '读取中' }}</strong></p>
      <Button type="primary" @click="showUpgrade">在线升级</Button>
    </div>
    <p v-if="job" class="mt-3 text-sm" role="status">{{ job.version }} · {{ phaseLabel }}</p>
    <Modal :open="open" title="在线升级" :width="600" :footer="null" @cancel="open = false">
      <Space direction="vertical" class="w-full" :size="16">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <p>当前版本 <strong>{{ info?.current_version || currentVersion || '读取中' }}</strong></p>
          <Button :loading="checking" :disabled="submitting" @click="checkUpdates()">检查更新</Button>
        </div>
        <Alert v-if="error" type="error" show-icon role="alert" :message="error" />
        <Alert v-if="reconnecting" type="info" show-icon role="status" message="服务暂时断开，正在重新连接并核对升级结果。" />
        <Alert v-if="info && !info.available" type="info" show-icon message="此部署尚未启用在线升级。" />
        <template v-else-if="info">
          <template v-if="info.candidates.length">
            <label for="system-upgrade-version" class="font-medium">选择版本</label>
            <select
              id="system-upgrade-version"
              v-model="selectedVersion"
              aria-label="升级目标版本"
              class="w-full rounded border border-border bg-background px-3 py-2"
              :disabled="running || submitting || uncertainSubmission"
            >
              <option v-for="candidate in info.candidates" :key="candidate.version" :value="candidate.version">{{ candidate.version }}</option>
            </select>
            <p v-if="selectedRelease?.notes" class="whitespace-pre-wrap text-sm text-muted-foreground">{{ selectedRelease.notes }}</p>
            <p class="text-sm text-muted-foreground">确认后将先备份数据，再更新服务。期间页面可能短暂断开，恢复后会继续显示升级结果。</p>
          </template>
          <p v-else>暂无可用更新。</p>
        </template>
        <div v-if="job" class="rounded border border-border p-3" role="status" aria-live="polite">
          <p><Tag :color="job.status === 'FAILED' ? 'error' : job.status === 'SUCCEEDED' ? 'success' : 'processing'">{{ phaseLabel }}</Tag>{{ job.version }}</p>
          <p v-if="job.status === 'FAILED'" class="mt-2 text-sm">升级未完成，请联系维护人员核对服务和备份后再重试。</p>
          <p v-if="job.status === 'SUCCEEDED'" class="mt-2 text-sm">服务已完成升级验证，可刷新页面使用新版本。</p>
        </div>
        <div class="flex justify-end gap-2">
          <Button :disabled="submitting" @click="open = false">关闭</Button>
          <Button type="primary" :loading="submitting" :disabled="!canSubmit" @click="startUpgrade">确认升级</Button>
        </div>
      </Space>
    </Modal>
  </Card>
</template>
