import { apiRequest } from './request';

export interface AdminSession {
  authenticated: boolean;
  mfa_required: boolean;
  admin?: { username: string };
  expires_at: string | null;
  recent_auth_until: string | null;
}

export interface LoginChallenge {
  authenticated?: boolean;
  admin?: { username: string };
  challenge_id?: string;
  mfa_required: boolean;
  totp_setup_required: boolean;
  expires_at: string;
}

export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
  expires_at: string;
}

export interface AuthenticatedSession extends AdminSession {
  authenticated: true;
  recovery_codes?: string[];
}

export interface LocalLoginCapability {
  enabled: boolean;
}

const post = <T>(path: string, body: Record<string, unknown>) =>
  apiRequest<T>(path, { method: 'POST', body: JSON.stringify(body) });

export const authApi = {
  session: () => apiRequest<AdminSession>('/api/v1/auth/session'),
  localLoginCapability: () =>
    apiRequest<LocalLoginCapability>('/api/v1/auth/local-login/status'),
  localLogin: () =>
    post<AuthenticatedSession>('/api/v1/auth/local-login', {}),
  login: (username: string, password: string) =>
    post<LoginChallenge>('/api/v1/auth/login', { username, password }),
  setupTotp: (challengeId: string) =>
    post<TotpSetup>('/api/v1/auth/totp/setup', { challenge_id: challengeId }),
  confirmTotp: (challengeId: string, code: string) =>
    post<AuthenticatedSession>('/api/v1/auth/totp/confirm', {
      challenge_id: challengeId,
      code,
    }),
  verifyTotp: (challengeId: string, code: string) =>
    post<AuthenticatedSession>('/api/v1/auth/totp/verify', {
      challenge_id: challengeId,
      code,
    }),
  recovery: (challengeId: string, code: string) =>
    post<AuthenticatedSession>('/api/v1/auth/recovery-code', {
      challenge_id: challengeId,
      code,
    }),
  logout: () => post<{ authenticated: false }>('/api/v1/auth/logout', {}),
};
