<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue';
import { AlertTriangle, RefreshCw, X } from 'lucide-vue-next';

import { Alert, Button, Descriptions, Form, Input, List, Modal, Space } from 'ant-design-vue';

import type { ActionPreview } from '@/api/resources';

interface ConfirmationPayload {
  preview_id: string;
  confirmation: string;
  idempotency_key: string;
}

const props = withDefaults(
  defineProps<{
    open: boolean;
    preview: ActionPreview | null;
    busy?: boolean;
    errorCode?: string;
    errorMessage?: string;
  }>(),
  { busy: false, errorCode: '', errorMessage: '' },
);
const emit = defineEmits<{
  close: [];
  refresh: [];
  confirm: [payload: ConfirmationPayload];
}>();

const typedPhrase = ref('');
const now = ref(Date.now());
const clock = window.setInterval(() => (now.value = Date.now()), 1000);
onScopeDispose(() => window.clearInterval(clock));

watch(
  () => props.preview?.id,
  () => {
    typedPhrase.value = '';
    now.value = Date.now();
  },
);

const expired = computed(
  () => !props.preview || now.value >= Date.parse(props.preview.expires_at),
);
const canSubmit = computed(
  () =>
    Boolean(props.preview) &&
    !expired.value &&
    !props.busy &&
    typedPhrase.value === props.preview?.required_phrase,
);
const impactedProfiles = computed(() => {
  const value = props.preview?.snapshot?.impacted_profiles;
  return Array.isArray(value) ? (value as Array<{ id: string; name: string }>) : [];
});
const expiryText = computed(() => {
  if (!props.preview) return '正在加载预览';
  if (expired.value) return '预览已过期';
  const seconds = Math.max(0, Math.ceil((Date.parse(props.preview.expires_at) - now.value) / 1000));
  return `预览将在 ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')} 后过期`;
});

function submit() {
  if (!canSubmit.value || !props.preview) return;
  emit('confirm', {
    preview_id: props.preview.id,
    confirmation: typedPhrase.value,
    idempotency_key: crypto.randomUUID(),
  });
}
</script>

<template>
  <Modal
    :open="open"
    :get-container="false"
    :destroy-on-close="true"
    :closable="false"
    :width="620"
    @cancel="emit('close')"
  >
    <template #title>
      <div class="flex items-center justify-between gap-4">
        <Space>
          <AlertTriangle :size="20" />
          <span id="danger-title">强制撤销访问</span>
        </Space>
        <Button type="text" aria-label="关闭" title="关闭" @click="emit('close')">
          <template #icon><X :size="18" /></template>
        </Button>
      </div>
    </template>
    <Space direction="vertical" class="w-full" :size="16">
      <p class="text-muted-foreground">链接会立即失效，节点凭据随后逐节点验证。</p>
      <Alert v-if="errorCode === 'STEP_UP_REQUIRED'" type="error" show-icon role="alert" message="近期身份验证已过期。请退出并重新完成密码与 MFA 验证后再次操作。" />
      <Alert v-else-if="errorMessage" type="error" show-icon role="alert" :message="errorMessage" />
      <Descriptions v-if="preview" bordered :column="1">
        <Descriptions.Item label="目标"><code class="break-all">{{ preview.target_id }}</code></Descriptions.Item>
        <Descriptions.Item label="有效期">
          <Alert v-if="expired" type="error" :message="expiryText" />
          <strong v-else>{{ expiryText }}</strong>
        </Descriptions.Item>
      </Descriptions>
      <Alert v-else type="info" show-icon message="正在生成绑定当前状态的预览..." />
      <Alert v-if="impactedProfiles.length" type="warning" show-icon message="共享凭据受影响身份" description="共享协议会轮换同节点凭据，以下有效设备需要重新导入新凭据。" />
      <List v-if="impactedProfiles.length" bordered :data-source="impactedProfiles">
        <template #renderItem="{ item }">
          <List.Item>
            <Space direction="vertical" :size="0">
              <strong>{{ item.name }}</strong>
              <code class="break-all text-muted-foreground">{{ item.id }}</code>
            </Space>
          </List.Item>
        </template>
      </List>
      <Form layout="vertical">
        <Form.Item>
          <template #label>输入 <strong>{{ preview?.required_phrase }}</strong> 继续</template>
          <Input v-model:value="typedPhrase" aria-label="确认文本" autocomplete="off" :disabled="!preview || expired || busy" />
        </Form.Item>
      </Form>
    </Space>
    <template #footer>
      <Space wrap>
        <Button v-if="expired" @click="emit('refresh')">
          <template #icon><RefreshCw :size="16" /></template>
          刷新预览
        </Button>
        <Button @click="emit('close')">取消</Button>
        <Button data-testid="danger-submit" type="primary" danger :disabled="!canSubmit" :loading="busy" @click="submit">
          {{ busy ? '提交中' : '提交操作' }}
        </Button>
      </Space>
    </template>
  </Modal>
</template>
