<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref } from 'vue';

import { Alert, Button, Input, Space, Tag } from 'ant-design-vue';

import { useSessionStore } from '@/stores/session';

const session = useSessionStore();
const password = ref('');
const code = ref('');
const enrollmentCode = ref('');
const busy = ref(false);
const errorMessage = ref('');
const setupExpiresAt = ref('');
const verified = ref(false);
let disposed = false;

const mfaEnabled = computed(() => session.session?.mfa_enabled !== false);
const enrollmentActive = computed(() => Boolean(session.sensitive.setupSecret));
const recoveryCodesVisible = computed(() => session.sensitive.recoveryCodes.length > 0);
const recentAuthAvailable = computed(() => {
  const until = session.session?.recent_auth_until;
  return Boolean(until && Date.now() < Date.parse(until));
});

onMounted(async () => {
  if (session.loaded) return;
  try {
    await session.loadSession();
  } catch {
    errorMessage.value = '无法读取当前认证状态，请刷新页面重试。';
  }
});
onScopeDispose(() => {
  disposed = true;
  password.value = '';
  code.value = '';
  enrollmentCode.value = '';
  session.clearSensitive();
});

function clearEnrollment() {
  session.clearSensitive();
  enrollmentCode.value = '';
  setupExpiresAt.value = '';
}

async function verifyIdentity() {
  if (busy.value) return;
  errorMessage.value = '';
  verified.value = false;
  if (!password.value || (mfaEnabled.value && !code.value)) {
    errorMessage.value = mfaEnabled.value ? '请输入当前密码和动态验证码。' : '请输入当前密码。';
    return;
  }
  busy.value = true;
  try {
    await session.stepUp(password.value, mfaEnabled.value ? code.value.trim() : undefined);
    if (!disposed) verified.value = true;
  } catch (error) {
    if (!disposed) errorMessage.value = error instanceof Error ? error.message : '身份验证失败';
  } finally {
    password.value = '';
    code.value = '';
    busy.value = false;
  }
}

async function beginEnrollment() {
  if (busy.value || mfaEnabled.value || !recentAuthAvailable.value) return;
  errorMessage.value = '';
  clearEnrollment();
  busy.value = true;
  try {
    const setup = await session.beginTotpSetup();
    if (disposed) session.clearSensitive();
    else setupExpiresAt.value = setup.expires_at;
  } catch (error) {
    if (!disposed) errorMessage.value = error instanceof Error ? error.message : '无法开始绑定';
  } finally {
    busy.value = false;
  }
}

async function confirmEnrollment() {
  if (busy.value || !enrollmentCode.value) return;
  errorMessage.value = '';
  busy.value = true;
  try {
    await session.confirmTotp(enrollmentCode.value.trim());
    if (disposed) session.clearSensitive();
  } catch (error) {
    if (!disposed) errorMessage.value = error instanceof Error ? error.message : '绑定验证失败';
  } finally {
    enrollmentCode.value = '';
    busy.value = false;
  }
}
</script>

<template>
  <section aria-labelledby="account-security-title" class="border-t border-border pt-5">
    <h2 id="account-security-title" class="mb-4 text-base font-semibold">账号安全</h2>
    <Space direction="vertical" class="w-full" :size="16">
      <p v-if="mfaEnabled"><Tag color="success">已绑定验证器</Tag>登录和敏感操作身份验证需要密码与动态验证码。</p>
      <p v-else><Tag>可选</Tag>未绑定验证器，使用密码登录。你可以自行选择绑定。</p>
      <Alert v-if="errorMessage" type="error" show-icon role="alert" :message="errorMessage" />
      <p v-if="verified" role="status">身份已验证，可以继续敏感操作；操作前仍需确认目标与预览。</p>
      <form data-testid="identity-step-up" class="grid max-w-lg gap-3" @submit.prevent="verifyIdentity">
        <label for="admin-stepup-password">当前密码</label>
        <Input.Password id="admin-stepup-password" v-model:value="password" aria-label="当前管理员密码" autocomplete="current-password" :disabled="busy" />
        <template v-if="mfaEnabled">
          <label for="admin-stepup-code">动态验证码</label>
          <Input id="admin-stepup-code" v-model:value="code" aria-label="当前动态验证码" inputmode="numeric" autocomplete="one-time-code" :disabled="busy" />
        </template>
        <Button type="primary" html-type="submit" :loading="busy">重新验证身份</Button>
      </form>
      <template v-if="recoveryCodesVisible">
        <Alert type="warning" show-icon role="note" message="请安全保存恢复码，关闭后不会再次显示。" />
        <ol class="grid gap-2 sm:grid-cols-2">
          <li v-for="item in session.sensitive.recoveryCodes" :key="item"><code>{{ item }}</code></li>
        </ol>
        <Button data-testid="acknowledge-optional-totp" @click="clearEnrollment">我已安全保存</Button>
      </template>
      <form v-else-if="enrollmentActive" data-testid="confirm-optional-totp" class="grid max-w-lg gap-3" @submit.prevent="confirmEnrollment">
        <p>在你的验证器中录入此绑定密钥，再输入动态验证码完成绑定：</p>
        <code class="break-all" aria-label="验证器绑定密钥">{{ session.sensitive.setupSecret }}</code>
        <p class="text-xs text-muted-foreground">绑定信息有效期至 {{ new Date(setupExpiresAt).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}。取消后仍使用密码登录。</p>
        <Input v-model:value="enrollmentCode" aria-label="绑定验证码" inputmode="numeric" autocomplete="one-time-code" :disabled="busy" />
        <Space>
          <Button type="primary" html-type="submit" :loading="busy">确认绑定</Button>
          <Button data-testid="cancel-optional-totp" :disabled="busy" @click="clearEnrollment">取消绑定</Button>
        </Space>
      </form>
      <template v-else-if="!mfaEnabled">
        <Button data-testid="begin-optional-totp" :disabled="busy || !recentAuthAvailable" :loading="busy" @click="beginEnrollment">绑定验证器（可选）</Button>
        <p v-if="!recentAuthAvailable" class="text-xs text-muted-foreground">绑定前请先验证当前密码。</p>
      </template>
    </Space>
  </section>
</template>
