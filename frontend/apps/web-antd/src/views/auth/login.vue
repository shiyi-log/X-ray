<script setup lang="ts">
import { computed, inject, ref } from 'vue';

import { AuthenticationLogin, z, type VbenFormSchema } from '@vben/common-ui';
import { Alert, Button, Form, Input } from 'ant-design-vue';
import { routerKey } from 'vue-router';

import { ApiError } from '@/api/request';
import { useSessionStore } from '@/stores/session';

type Phase = 'password' | 'totp' | 'setup' | 'recovery' | 'recovery-codes';

const session = useSessionStore();
const router = inject(routerKey, undefined);
const phase = ref<Phase>('password');
const loginForm = ref<InstanceType<typeof AuthenticationLogin>>();
const formSchema: VbenFormSchema[] = [
  {
    component: 'VbenInput',
    componentProps: { autocomplete: 'username', placeholder: '管理员账号', 'data-testid': 'username', 'aria-label': '管理员账号' },
    fieldName: 'username', label: '管理员账号',
    rules: z.string().min(1, '请输入管理员账号'),
  },
  {
    component: 'VbenInputPassword',
    componentProps: { autocomplete: 'current-password', placeholder: '密码', 'data-testid': 'password', 'aria-label': '密码' },
    fieldName: 'password', label: '密码',
    rules: z.string().min(1, '请输入密码'),
  },
];
const code = ref('');
const preferRecovery = ref(false);
const submitting = ref(false);
const errorMessage = ref('');

const title = computed(() => {
  if (phase.value === 'setup') return '绑定身份验证器';
  if (phase.value === 'totp') return '输入动态验证码';
  if (phase.value === 'recovery') return '使用恢复码';
  if (phase.value === 'recovery-codes') return '保存恢复码';
  return '管理员登录';
});

function showError(error: unknown) {
  errorMessage.value =
    error instanceof ApiError || error instanceof Error ? error.message : '请求失败';
}

async function finishAuthentication() {
  const redirect = String(router?.currentRoute.value.query.redirect || '/overview');
  await router?.replace(redirect);
}

async function submitPassword(values: Record<string, unknown>) {
  if (submitting.value) return;
  errorMessage.value = '';
  submitting.value = true;
  try {
    const challenge = await session.passwordLogin(String(values.username || ''), String(values.password || ''));
    if (challenge.authenticated) {
      await finishAuthentication();
    } else if (challenge.totp_setup_required) {
      await session.beginTotpSetup();
      phase.value = 'setup';
    } else {
      phase.value = preferRecovery.value ? 'recovery' : 'totp';
    }
  } catch (error) {
    showError(error);
  } finally {
    await loginForm.value?.getFormApi().setFieldValue('password', '');
    submitting.value = false;
  }
}

async function submitSecondFactor() {
  errorMessage.value = '';
  submitting.value = true;
  try {
    if (phase.value === 'setup') {
      const result = await session.confirmTotp(code.value);
      code.value = '';
      if (result.recovery_codes?.length) {
        phase.value = 'recovery-codes';
        return;
      }
    } else if (phase.value === 'recovery') {
      await session.useRecoveryCode(code.value.trim());
    } else {
      await session.verifyTotp(code.value.trim());
    }
    code.value = '';
    await finishAuthentication();
  } catch (error) {
    showError(error);
  } finally {
    submitting.value = false;
  }
}

function selectRecovery() {
  preferRecovery.value = true;
  phase.value = session.sensitive.challengeId ? 'recovery' : 'password';
}

async function acknowledgeRecoveryCodes() {
  session.clearSensitive();
  await finishAuthentication();
}
</script>

<template>
  <div>
    <Alert v-if="errorMessage" class="mb-4" type="error" show-icon :message="errorMessage" role="alert" />
    <AuthenticationLogin
      v-if="phase === 'password'"
      ref="loginForm"
      data-testid="password-submit"
      :form-schema="formSchema"
      :loading="submitting"
      :show-code-login="false"
      :show-forget-password="false"
      :show-qrcode-login="false"
      :show-register="false"
      :show-remember-me="false"
      :show-third-party-login="false"
      :submit-button-text="preferRecovery ? '继续使用恢复码' : '登录'"
      title="管理员登录"
      sub-title="验证管理员账号后，按账户状态完成多因素校验。"
      @submit="submitPassword"
    />
    <template v-else>
      <header class="mb-7">
        <h1 class="mb-3 text-3xl font-bold tracking-tight">{{ title }}</h1>
        <p class="text-muted-foreground">{{ phase === 'recovery-codes' ? '这些恢复码关闭后不会再次显示' : '完成身份验证后进入控制台' }}</p>
      </header>
      <Form v-if="phase !== 'recovery-codes'" class="xray-login-step" layout="vertical" :model="{ code }" @finish="submitSecondFactor">
        <Alert v-if="phase === 'setup'" class="mb-4" type="info" message="绑定密钥" :description="session.sensitive.setupSecret" />
        <Form.Item name="code" :label="phase === 'recovery' ? '恢复码' : '6 位动态验证码'" :rules="[{ required: true, message: '请输入验证码' }]">
          <Input
            v-model:value="code"
            :data-testid="phase === 'recovery' ? 'recovery-code' : 'totp-code'"
            :inputmode="phase === 'recovery' ? 'text' : 'numeric'"
            autocomplete="one-time-code"
          />
        </Form.Item>
        <Button type="primary" html-type="submit" block :loading="submitting">验证并登录</Button>
      </Form>
      <section v-else>
        <ol class="mb-6 grid grid-cols-2 gap-3">
          <li v-for="item in session.sensitive.recoveryCodes" :key="item"><code>{{ item }}</code></li>
        </ol>
        <Button type="primary" block @click="acknowledgeRecoveryCodes">我已安全保存</Button>
      </section>
    </template>
    <Button
      v-if="phase !== 'setup' && phase !== 'recovery-codes'"
      data-testid="use-recovery"
      class="mt-4"
      type="link"
      block
      @click="selectRecovery"
    >
      使用恢复码
    </Button>
  </div>
</template>
