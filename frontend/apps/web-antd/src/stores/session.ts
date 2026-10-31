import { defineStore } from 'pinia';

import { useTabbarStore, useUserStore } from '@vben/stores';

import { authApi, type AdminSession, type LoginChallenge, type TotpSetup } from '@/api/auth';
import { clearSensitiveState, registerSensitiveClearer } from '@/api/request';

interface SensitiveAuthState {
  challengeId: string;
  setupSecret: string;
  setupUri: string;
  recoveryCodes: string[];
}

const emptySensitiveState = (): SensitiveAuthState => ({
  challengeId: '',
  setupSecret: '',
  setupUri: '',
  recoveryCodes: [],
});

export const useSessionStore = defineStore('session', {
  state: () => ({
    loaded: false,
    loading: false,
    session: null as AdminSession | null,
    sensitive: emptySensitiveState(),
  }),
  getters: {
    authenticated: (state) => Boolean(state.session?.authenticated),
    username: (state) => state.session?.admin?.username || '',
  },
  actions: {
    applySession(session: AdminSession | null) {
      this.session = session;
      this.loaded = true;
      const username = session?.authenticated ? session.admin?.username : undefined;
      useUserStore().setUserInfo(username ? {
        avatar: '',
        realName: username,
        userId: username,
        username,
      } : null);
    },
    clearSensitive() {
      this.sensitive = emptySensitiveState();
    },
    async loadSession() {
      this.loading = true;
      try {
        const session = await authApi.session();
        this.applySession(session);
        return session;
      } finally {
        this.loading = false;
      }
    },
    async localOneClickLogin() {
      this.clearSensitive();
      const authenticated = await authApi.localLogin();
      this.applySession(authenticated);
      return authenticated;
    },
    async passwordLogin(username: string, password: string): Promise<LoginChallenge> {
      this.clearSensitive();
      const challenge = await authApi.login(username, password);
      this.sensitive.challengeId = challenge.challenge_id || '';
      if (challenge.authenticated) {
        this.applySession({
          authenticated: true,
          mfa_required: false,
          admin: challenge.admin,
          expires_at: challenge.expires_at,
          recent_auth_until: null,
        });
      }
      return challenge;
    },
    async beginTotpSetup(): Promise<TotpSetup> {
      const setup = await authApi.setupTotp(this.sensitive.challengeId);
      this.sensitive.setupSecret = setup.secret;
      this.sensitive.setupUri = setup.otpauth_uri;
      return setup;
    },
    async confirmTotp(code: string) {
      const result = await authApi.confirmTotp(this.sensitive.challengeId, code);
      this.applySession(result);
      this.sensitive.recoveryCodes = result.recovery_codes || [];
      this.sensitive.challengeId = '';
      this.sensitive.setupSecret = '';
      this.sensitive.setupUri = '';
      return result;
    },
    async verifyTotp(code: string) {
      const result = await authApi.verifyTotp(this.sensitive.challengeId, code);
      this.applySession(result);
      this.clearSensitive();
      return result;
    },
    async useRecoveryCode(code: string) {
      const result = await authApi.recovery(this.sensitive.challengeId, code);
      this.applySession(result);
      this.clearSensitive();
      return result;
    },
    async logout() {
      try {
        await authApi.logout();
      } finally {
        useUserStore().setUserInfo(null);
        useTabbarStore().$reset();
        this.$reset();
        clearSensitiveState();
      }
    },
    installUnauthorizedHandler() {
      registerSensitiveClearer(() => {
        useUserStore().setUserInfo(null);
        useTabbarStore().$reset();
        this.session = null;
        this.loaded = true;
        this.clearSensitive();
      });
    },
  },
});

export async function loadSession(): Promise<AdminSession> {
  return useSessionStore().loadSession();
}
