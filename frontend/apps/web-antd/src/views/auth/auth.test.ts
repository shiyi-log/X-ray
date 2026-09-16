import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

import LoginView from './login.vue';

describe('安全登录', () => {
  beforeEach(() => setActivePinia(createPinia()));

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
    const wrapper = mount(LoginView, {
      global: { plugins: [createPinia()] },
    });

    await wrapper.get('[data-testid="username"]').setValue('admin');
    await wrapper.get('[data-testid="password"]').setValue('correct horse battery staple');
    await wrapper.get('[data-testid="password-submit"]').trigger('submit');
    await flushPromises();

    expect(wrapper.find('[data-testid="totp-code"]').exists()).toBe(true);
    expect(localStorage.getItem('accessToken')).toBeNull();
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
    const wrapper = mount(LoginView, {
      global: { plugins: [createPinia()] },
    });
    await wrapper.get('[data-testid="use-recovery"]').trigger('click');
    await wrapper.get('[data-testid="username"]').setValue('admin');
    await wrapper.get('[data-testid="password"]').setValue('correct horse battery staple');
    await wrapper.get('[data-testid="password-submit"]').trigger('submit');
    await flushPromises();
    expect(wrapper.get('[data-testid="recovery-code"]').attributes('autocomplete')).toBe(
      'one-time-code',
    );
    expect(wrapper.find('[data-testid="totp-code"]').exists()).toBe(false);
  });
});
