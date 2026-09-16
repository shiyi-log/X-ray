export interface ApiErrorPayload {
  code: string;
  message: string;
  retryable?: boolean;
  operation_id?: string | null;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  readonly operationId: string | null;
  readonly details: Record<string, unknown>;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message || '请求失败');
    this.name = 'ApiError';
    this.status = status;
    this.code = payload.code || 'REQUEST_FAILED';
    this.retryable = Boolean(payload.retryable);
    this.operationId = payload.operation_id ?? null;
    this.details = payload.details ?? {};
  }
}

let csrfToken: string | null = null;
let csrfPromise: Promise<string> | null = null;
const sensitiveStateClearers = new Set<() => void>();

const writeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function purgeLegacyBrowserSecrets() {
  for (const key of ['accessToken', 'refreshToken', 'token', 'subscriptionToken']) {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  }
}

function performSensitiveClear() {
  csrfToken = null;
  csrfPromise = null;
  purgeLegacyBrowserSecrets();
  for (const clearer of sensitiveStateClearers) clearer();
}

export function clearSensitiveState(clearer?: () => void) {
  if (clearer) sensitiveStateClearers.add(clearer);
  performSensitiveClear();
}

export function registerSensitiveClearer(clearer: () => void) {
  sensitiveStateClearers.add(clearer);
  return () => sensitiveStateClearers.delete(clearer);
}

export function resetCsrfToken() {
  csrfToken = null;
  csrfPromise = null;
}

async function loadCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  if (!csrfPromise) {
    csrfPromise = fetch('/api/v1/auth/csrf', {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error('无法初始化请求校验');
        const payload = (await response.json()) as { csrf_token?: string };
        if (!payload.csrf_token) throw new Error('请求校验响应无效');
        csrfToken = payload.csrf_token;
        return csrfToken;
      })
      .finally(() => {
        csrfPromise = null;
      });
  }
  return csrfPromise;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204 || response.headers.get('Content-Length') === '0') {
    return undefined;
  }
  const contentType = response.headers.get('Content-Type') || '';
  return contentType.includes('json') ? response.json() : response.text();
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  retryCsrf = true,
): Promise<T> {
  const method = String(init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (writeMethods.has(method)) {
    headers.set('X-CSRFToken', await loadCsrfToken());
  }

  const response = await fetch(path, {
    ...init,
    method,
    credentials: 'same-origin',
    headers,
  });
  const payload = await parseBody(response);

  if (response.ok) return payload as T;

  const errorPayload: ApiErrorPayload =
    payload && typeof payload === 'object'
      ? (payload as ApiErrorPayload)
      : { code: 'REQUEST_FAILED', message: '请求失败' };

  if (response.status === 401) performSensitiveClear();
  if (response.status === 403 && errorPayload.code === 'CSRF_FAILED' && retryCsrf) {
    resetCsrfToken();
    return apiRequest<T>(path, init, false);
  }
  throw new ApiError(response.status, errorPayload);
}
