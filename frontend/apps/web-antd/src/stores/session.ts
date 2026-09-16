import { defineStore } from 'pinia';

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
    clearSensitive() {
      this.sensitive = emptySensitiveState();
    },
    async loadSession() {
      this.loading = true;
      try {
        this.session = await authApi.session();
        this.loaded = true;
        return this.session;
      } finally {
        this.loading = false;
      }
    },
    async passwordLogin(username: string, password: string): Promise<LoginChallenge> {
      this.clearSensitive();
      const challenge = await authApi.login(username, password);
      this.sensitive.challengeId = challenge.challenge_id;
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
      this.session = result;
      this.sensitive.recoveryCodes = result.recovery_codes || [];
      this.sensitive.challengeId = '';
      this.sensitive.setupSecret = '';
      this.sensitive.setupUri = '';
      return result;
    },
    async verifyTotp(code: string) {
      const result = await authApi.verifyTotp(this.sensitive.challengeId, code);
      this.session = result;
      this.clearSensitive();
      return result;
    },
    async useRecoveryCode(code: string) {
      const result = await authApi.recovery(this.sensitive.challengeId, code);
      this.session = result;
      this.clearSensitive();
      return result;
    },
    async logout() {
      try {
        await authApi.logout();
      } finally {
        this.$reset();
        clearSensitiveState();
      }
    },
    installUnauthorizedHandler() {
      registerSensitiveClearer(() => {
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
