<script setup lang="ts">
import { computed, inject, ref } from 'vue';
import { routerKey } from 'vue-router';
import { KeyRound, LockKeyhole, ShieldCheck, UserRound } from 'lucide-vue-next';

import { ApiError } from '@/api/request';
import { useSessionStore } from '@/stores/session';

type Phase = 'password' | 'totp' | 'setup' | 'recovery' | 'recovery-codes';

const session = useSessionStore();
const router = inject(routerKey, undefined);
const phase = ref<Phase>('password');
const username = ref('');
const password = ref('');
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

async function submitPassword() {
  errorMessage.value = '';
  submitting.value = true;
  try {
    const challenge = await session.passwordLogin(username.value, password.value);
    password.value = '';
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
  <main class="auth-page">
    <section class="auth-panel" aria-labelledby="auth-title">
      <div class="brand-mark" aria-hidden="true"><ShieldCheck :size="26" /></div>
      <div class="brand-copy">
        <strong>X-ray</strong>
        <span>管理平台</span>
      </div>

      <header>
        <h1 id="auth-title">{{ title }}</h1>
        <p v-if="phase === 'password'">使用唯一管理员账户进入控制台</p>
        <p v-else-if="phase === 'setup'">密钥仅在当前绑定流程显示</p>
        <p v-else-if="phase === 'recovery-codes'">这些恢复码关闭后不会再次显示</p>
        <p v-else>完成第二阶段验证后建立服务器会话</p>
      </header>

      <div v-if="errorMessage" class="error-band" role="alert">{{ errorMessage }}</div>

      <form
        v-if="phase === 'password'"
        data-testid="password-submit"
        class="auth-form"
        @submit.prevent="submitPassword"
      >
        <label>
          <span>管理员账号</span>
          <span class="input-shell"><UserRound :size="17" /><input
            v-model="username"
            data-testid="username"
            autocomplete="username"
            required
          /></span>
        </label>
        <label>
          <span>密码</span>
          <span class="input-shell"><LockKeyhole :size="17" /><input
            v-model="password"
            data-testid="password"
            type="password"
            autocomplete="current-password"
            required
          /></span>
        </label>
        <button class="primary-button" type="submit" :disabled="submitting">
          {{ submitting ? '验证中' : preferRecovery ? '继续使用恢复码' : '继续' }}
        </button>
      </form>

      <form
        v-else-if="phase === 'totp' || phase === 'setup' || phase === 'recovery'"
        class="auth-form"
        @submit.prevent="submitSecondFactor"
      >
        <div v-if="phase === 'setup'" class="setup-secret">
          <span>绑定密钥</span>
          <code>{{ session.sensitive.setupSecret }}</code>
        </div>
        <label>
          <span>{{ phase === 'recovery' ? '恢复码' : '6 位动态验证码' }}</span>
          <span class="input-shell"><KeyRound :size="17" /><input
            v-model="code"
            :data-testid="phase === 'recovery' ? 'recovery-code' : 'totp-code'"
            :inputmode="phase === 'recovery' ? 'text' : 'numeric'"
            autocomplete="one-time-code"
            required
          /></span>
        </label>
        <button class="primary-button" type="submit" :disabled="submitting">
          {{ submitting ? '验证中' : '验证并登录' }}
        </button>
      </form>

      <section v-else class="recovery-list">
        <ol>
          <li v-for="item in session.sensitive.recoveryCodes" :key="item"><code>{{ item }}</code></li>
        </ol>
        <button class="primary-button" type="button" @click="acknowledgeRecoveryCodes">
          我已安全保存
        </button>
      </section>

      <button
        v-if="phase !== 'setup' && phase !== 'recovery-codes'"
        data-testid="use-recovery"
        class="text-button"
        type="button"
        @click="selectRecovery"
      >
        使用恢复码
      </button>
    </section>
  </main>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px 20px;
  background: #eef2f4;
  color: var(--x-text);
}

.auth-panel {
  width: min(100%, 408px);
  padding: 34px 36px 30px;
  background: var(--x-surface);
  border: 1px solid var(--x-border);
  border-radius: var(--x-radius);
  box-shadow: var(--x-shadow);
}

.brand-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  color: white;
  background: var(--x-accent);
  border-radius: 5px;
}

.brand-copy {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 14px;
}

.brand-copy strong { font-size: 19px; }
.brand-copy span { color: var(--x-text-muted); font-size: 13px; }
header { margin: 32px 0 24px; }
h1 { margin: 0; font-size: 24px; line-height: 1.3; letter-spacing: 0; }
header p { margin: 8px 0 0; color: var(--x-text-muted); font-size: 14px; }
.auth-form { display: grid; gap: 18px; }
label { display: grid; gap: 7px; font-size: 13px; font-weight: 600; }

.input-shell {
  height: 42px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  color: var(--x-text-muted);
  border: 1px solid #cbd5dc;
  border-radius: 5px;
  background: white;
}

.input-shell:focus-within { border-color: var(--x-accent); box-shadow: 0 0 0 3px rgb(8 127 140 / 12%); }
input { min-width: 0; flex: 1; border: 0; outline: 0; font: inherit; color: var(--x-text); }

.primary-button {
  min-height: 42px;
  border: 0;
  border-radius: 5px;
  background: var(--x-accent);
  color: white;
  font: 600 14px/1 var(--x-font);
  cursor: pointer;
}

.primary-button:disabled { opacity: .6; cursor: wait; }
.text-button { margin: 18px auto 0; display: block; border: 0; background: transparent; color: var(--x-accent); cursor: pointer; font: 500 13px/1.4 var(--x-font); }
.error-band { margin-bottom: 18px; padding: 10px 12px; border-left: 3px solid var(--x-danger); background: #fff1f0; color: #8f1d14; font-size: 13px; }
.setup-secret { padding: 12px; border: 1px solid var(--x-border); background: var(--x-surface-muted); overflow-wrap: anywhere; }
.setup-secret span { display: block; margin-bottom: 6px; color: var(--x-text-muted); font-size: 12px; }
.recovery-list ol { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 22px; padding-left: 22px; }
.recovery-list code { font-size: 12px; }

@media (max-width: 520px) {
  .auth-page { padding: 0; background: white; align-items: stretch; }
  .auth-panel { width: 100%; padding: 28px 24px; border: 0; box-shadow: none; }
  .recovery-list ol { grid-template-columns: 1fr; }
}
</style>
