import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';

import LoginView from './login.vue';

async function mountLogin() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: { template: '<div />' } },
      { path: '/overview', component: { template: '<div />' } },
    ],
  });
  await router.push('/login?redirect=/overview');
  const wrapper = mount(LoginView, {
    global: { plugins: [createPinia(), router] },
  });
  return { wrapper, router };
}

describe('安全登录', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('本地密码直登沿用官方表单，跳转目标且不保存密码', async () => {
    const password = 'test-only-local-password';
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).endsWith('/csrf')
        ? { csrf_token: 'csrf' }
        : { authenticated: true, mfa_required: false, admin: { username: 'admin' } };
      return new Response(JSON.stringify(body), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetch);
    const { wrapper, router } = await mountLogin();
    try {
      await wrapper.get('[data-testid="username"]').setValue('admin');
      await wrapper.get('[data-testid="password"]').setValue(password);
      await wrapper.get('[aria-label="login"]').trigger('click');
      await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/overview'));
      expect(wrapper.find('[data-testid="totp-code"]').exists()).toBe(false);
      expect((wrapper.get('[data-testid="password"]').element as HTMLInputElement).value).toBe('');
      expect(JSON.stringify({ ...localStorage })).not.toContain(password);
      expect(JSON.stringify({ ...sessionStorage })).not.toContain(password);
      expect(localStorage.getItem('accessToken')).toBeNull();
    } finally {
      wrapper.unmount();
    }
  });

  it('密码阶段只进入 MFA，不创建前端令牌', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/csrf')) {
          return new Response(JSON.stringify({ csrf_token: 'csrf' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response(
          JSON.stringify({
            challenge_id: '11111111-1111-4111-8111-111111111111',
            mfa_required: true,
            totp_setup_required: false,
            expires_at: '2026-09-17T12:00:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );
    const { wrapper } = await mountLogin();

    await wrapper.get('[data-testid="username"]').setValue('admin');
    await wrapper.get('[data-testid="password"]').setValue('correct horse battery staple');
    await wrapper.get('[aria-label="login"]').trigger('click');
    await flushPromises();

    await vi.waitFor(() => expect(wrapper.find('[data-testid="totp-code"]').exists()).toBe(true));
    expect(localStorage.getItem('accessToken')).toBeNull();
    wrapper.unmount();
  });

  it('恢复码路径明确且不与 TOTP 输入混用', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/csrf')) {
          return new Response(JSON.stringify({ csrf_token: 'csrf' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response(
          JSON.stringify({
            challenge_id: '11111111-1111-4111-8111-111111111111',
            mfa_required: true,
            totp_setup_required: false,
            expires_at: '2026-09-17T12:00:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );
    const { wrapper } = await mountLogin();
    await wrapper.get('[data-testid="use-recovery"]').trigger('click');
    await wrapper.get('[data-testid="username"]').setValue('admin');
    await wrapper.get('[data-testid="password"]').setValue('correct horse battery staple');
    await wrapper.get('[aria-label="login"]').trigger('click');
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.find('[data-testid="recovery-code"]').exists()).toBe(true));
    expect(wrapper.get('[data-testid="recovery-code"]').attributes('autocomplete')).toBe(
      'one-time-code',
    );
    expect(wrapper.find('[data-testid="totp-code"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
