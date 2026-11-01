<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue';
import { Check, Clipboard, KeyRound, X } from 'lucide-vue-next';

import { Alert, Button, Descriptions, Modal, Space } from 'ant-design-vue';

import type { SecretDelivery as SecretDeliveryValue } from '@/api/resources';
import { registerSensitiveClearer } from '@/api/request';

const props = defineProps<{ open: boolean; delivery: SecretDeliveryValue | null }>();
const emit = defineEmits<{ close: [] }>();
const secret = ref<SecretDeliveryValue | null>(null);
const copied = ref('');
const copyError = ref('');
let timer: number | undefined;

function wipe() {
  secret.value = null;
  copied.value = '';
  copyError.value = '';
  if (timer) window.clearTimeout(timer);
  timer = undefined;
}

function close() {
  wipe();
  emit('close');
}

watch(
  () => [props.open, props.delivery] as const,
  ([open, value]) => {
    wipe();
    if (!open || !value) return;
    secret.value = { ...value };
    timer = window.setTimeout(close, 5 * 60 * 1000);
  },
  { immediate: true },
);

const unregister = registerSensitiveClearer(() => {
  if (secret.value || props.open) close();
});
onScopeDispose(() => {
  unregister();
  wipe();
});

const unifiedUrl = computed(() => secret.value?.url || null);

async function copy(label: string, value: string) {
  copyError.value = '';
  try { await navigator.clipboard.writeText(value); }
  catch { copyError.value = '剪贴板不可用，请手动复制订阅链接。'; return; }
  copied.value = label;
  window.setTimeout(() => {
    if (copied.value === label) copied.value = '';
  }, 1600);
}
</script>

<template>
  <Modal
    v-if="open && secret"
    :open="true"
    :get-container="false"
    :destroy-on-close="true"
    :closable="false"
    :mask-closable="false"
    :keyboard="false"
    :width="720"
    @cancel="close"
  >
    <template #title>
      <div class="flex items-center justify-between gap-4">
        <Space>
          <KeyRound :size="20" />
          <span id="secret-title">一次性交付</span>
        </Space>
        <Button type="text" aria-label="关闭" title="关闭" @click="close">
          <template #icon><X :size="18" /></template>
        </Button>
      </div>
    </template>
    <Space direction="vertical" class="w-full" :size="16">
      <p class="text-muted-foreground">关闭或五分钟后清除，之后只能显式轮换。</p>
      <Alert type="warning" show-icon message="Token 与订阅 URL 不会写入浏览器存储，也无法从服务器再次读取。" />
      <Alert v-if="copyError" type="error" :message="copyError" />
      <Alert type="info" message="统一链接默认返回 Mihomo 配置，包含所有已发布且受支持的协议。" />
      <Descriptions :column="1" bordered layout="vertical">
        <Descriptions.Item label="Token">
          <div class="flex items-start justify-between gap-3">
            <code class="min-w-0 break-all">{{ secret.token }}</code>
            <Button data-testid="copy-token" @click="copy('token', secret.token)">
              <template #icon>
                <Check v-if="copied === 'token'" :size="16" />
                <Clipboard v-else :size="16" />
              </template>
              {{ copied === 'token' ? '已复制' : '复制' }}
            </Button>
          </div>
        </Descriptions.Item>
        <Descriptions.Item v-if="unifiedUrl" label="统一订阅链接">
          <div class="flex items-start justify-between gap-3">
            <code data-testid="unified-url" class="min-w-0 break-all">{{ unifiedUrl }}</code>
            <Button aria-label="复制统一订阅链接" title="复制统一订阅链接" @click="copy('unified-url', unifiedUrl)">
              <template #icon>
                <Check v-if="copied === 'unified-url'" :size="16" />
                <Clipboard v-else :size="16" />
              </template>
            </Button>
          </div>
        </Descriptions.Item>
      </Descriptions>
    </Space>
    <template #footer>
      <Button type="primary" @click="close">我已安全保存并关闭</Button>
    </template>
  </Modal>
</template>
