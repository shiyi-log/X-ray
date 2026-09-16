import { apiRequest, clearSensitiveState, resetCsrfToken } from './request';

describe('apiRequest', () => {
  beforeEach(() => resetCsrfToken());

  it('写请求携带同源 cookie 与内存 CSRF，且不写登录令牌', async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ input, init });
        if (String(input).endsWith('/api/v1/auth/csrf')) {
          return new Response(JSON.stringify({ csrf_token: 'csrf-for-test' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response(
          JSON.stringify({ mfa_required: true, authenticated: false }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );

    await apiRequest('/api/v1/auth/login', { method: 'POST', body: '{}' });

    expect(calls).toHaveLength(2);
    expect(calls[1]?.init?.credentials).toBe('same-origin');
    expect(new Headers(calls[1]?.init?.headers).get('X-CSRFToken')).toBe('csrf-for-test');
    expect(localStorage.getItem('accessToken')).toBeNull();
  });

  it('401 清除敏感内存与遗留 Web Storage', async () => {
    localStorage.setItem('accessToken', 'legacy-value');
    let cleared = false;
    clearSensitiveState(() => {
      cleared = true;
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ code: 'AUTH_REQUIRED', message: '需要登录' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    await expect(apiRequest('/api/v1/auth/session')).rejects.toMatchObject({
      code: 'AUTH_REQUIRED',
    });
    expect(localStorage.getItem('accessToken')).toBeNull();
    expect(cleared).toBe(true);
  });

  it('CSRF 失败最多刷新并重试一次', async () => {
    let csrfCalls = 0;
    let writeCalls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/api/v1/auth/csrf')) {
          csrfCalls += 1;
          return new Response(JSON.stringify({ csrf_token: `csrf-${csrfCalls}` }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        writeCalls += 1;
        return new Response(JSON.stringify({ code: 'CSRF_FAILED', message: '刷新' }), {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        });
      }),
    );

    await expect(
      apiRequest('/api/v1/auth/login', { method: 'POST', body: '{}' }),
    ).rejects.toMatchObject({ code: 'CSRF_FAILED' });
    expect(csrfCalls).toBe(2);
    expect(writeCalls).toBe(2);
  });
});
