<script setup lang="ts">
import { onScopeDispose, ref, useId, watch } from 'vue';

import { Alert, Button, Input, Modal, Space } from 'ant-design-vue';

import { ApiError, registerSensitiveClearer } from '@/api/request';
import { useSessionStore } from '@/stores/session';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; verified: [] }>();
const session = useSessionStore();
const inputId = useId();
const password = ref('');
const code = ref('');
const errorMessage = ref('');
const loading = ref(false);
const busy = ref(false);
const sessionReady = ref(false);
const mfaEnabled = ref(true);
let generation = 0;
let disposed = false;

function clearCredentials() {
  password.value = '';
  code.value = '';
}

function invalidate() {
  generation += 1;
  clearCredentials();
  sessionReady.value = false;
  loading.value = false;
  busy.value = false;
}

function current(attempt: number) {
  return !disposed && props.open && generation === attempt;
}

const unregister = registerSensitiveClearer(() => {
  invalidate();
  if (props.open) emit('close');
});

watch(() => props.open, async (open) => {
  invalidate();
  errorMessage.value = '';
  if (!open) return;
  const attempt = generation;
  loading.value = true;
  try {
    const state = await session.loadSession();
    if (!current(attempt)) return;
    if (!state.authenticated) {
      errorMessage.value = '当前会话已失效，请重新登录。';
    } else if (typeof state.mfa_enabled !== 'boolean') {
      errorMessage.value = '无法确认当前认证状态，请关闭后重试。';
    } else {
      mfaEnabled.value = state.mfa_enabled;
      sessionReady.value = true;
    }
  } catch {
    if (current(attempt)) errorMessage.value = '无法读取当前认证状态，请关闭后重试。';
  } finally {
    if (current(attempt)) loading.value = false;
  }
}, { immediate: true });

onScopeDispose(() => {
  disposed = true;
  unregister();
  invalidate();
});

function close() {
  invalidate();
  emit('close');
}

async function verify() {
  if (!props.open || !sessionReady.value || busy.value || loading.value) return;
  errorMessage.value = '';
  if (!password.value || (mfaEnabled.value && !code.value.trim())) {
    errorMessage.value = mfaEnabled.value ? '请输入当前密码和动态验证码。' : '请输入当前密码。';
    return;
  }
  const attempt = generation;
  busy.value = true;
  try {
    await session.stepUp(password.value, mfaEnabled.value ? code.value.trim() : undefined);
    if (current(attempt)) emit('verified');
  } catch (error) {
    if (current(attempt)) {
      errorMessage.value = error instanceof ApiError && error.status === 429
        ? '身份验证过于频繁，请稍后重试。'
        : '身份验证失败，请检查输入后重试。';
    }
  } finally {
    if (current(attempt)) {
      clearCredentials();
      busy.value = false;
    }
  }
}
</script>

<template>
  <Modal
    :open="open"
    title="重新验证身份"
    :footer="null"
    :get-container="false"
    :destroy-on-close="true"
    :mask-closable="false"
    :width="440"
    @cancel="close"
  >
    <p class="mb-4 text-muted-foreground">为保护订阅和账号，请验证当前身份后继续操作。</p>
    <Alert v-if="errorMessage" class="mb-4" type="error" show-icon role="alert" :message="errorMessage" />
    <p v-if="loading" class="mb-4" role="status">正在确认认证状态…</p>
    <form class="grid gap-3" @submit.prevent="verify">
      <label :for="`${inputId}-password`">当前密码</label>
      <Input.Password
        :id="`${inputId}-password`"
        v-model:value="password"
        aria-label="当前管理员密码"
        autocomplete="current-password"
        :disabled="!sessionReady || busy"
      />
      <template v-if="sessionReady && mfaEnabled">
        <label :for="`${inputId}-code`">动态验证码</label>
        <Input
          :id="`${inputId}-code`"
          v-model:value="code"
          aria-label="当前动态验证码"
          inputmode="numeric"
          autocomplete="one-time-code"
          :disabled="busy"
        />
      </template>
      <Space class="mt-2 justify-end">
        <Button data-testid="step-up-cancel" @click="close">取消</Button>
        <Button type="primary" html-type="submit" :loading="busy" :disabled="!sessionReady || busy">验证身份</Button>
      </Space>
    </form>
  </Modal>
</template>
