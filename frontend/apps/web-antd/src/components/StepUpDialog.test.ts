import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

import { authApi, type AdminSession } from '@/api/auth';
import { apiRequest, clearSensitiveState } from '@/api/request';
import { useSessionStore } from '@/stores/session';

import StepUpDialog from './StepUpDialog.vue';

const sessionFixture = (mfaEnabled = false): AdminSession => ({
  authenticated: true, mfa_required: false, mfa_enabled: mfaEnabled,
  admin: { username: 'fixture-admin' }, expires_at: '2035-11-15T12:00:00Z',
  recent_auth_until: null,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

async function openDialog(mfaEnabled = false) {
  vi.spyOn(authApi, 'session').mockResolvedValue(sessionFixture(mfaEnabled));
  const wrapper = mount(StepUpDialog, { props: { open: false }, attachTo: document.body });
  await wrapper.setProps({ open: true });
  await flushPromises();
  return wrapper;
}

describe('StepUpDialog', () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => vi.unstubAllGlobals());

  it('verifies an unbound administrator using the password and only then emits verified', async () => {
    vi.spyOn(authApi, 'stepUp').mockResolvedValue({ recent_auth_until: '2035-11-15T11:30:00Z' });
    const wrapper = await openDialog();
    try {
      expect(wrapper.find('[aria-label="当前动态验证码"]').exists()).toBe(false);
      await wrapper.get('[aria-label="当前管理员密码"]').setValue('fixture-password');
      expect(wrapper.emitted('verified')).toBeUndefined();
      await wrapper.get('form').trigger('submit');
      await flushPromises();
      expect(authApi.stepUp).toHaveBeenCalledWith('fixture-password', undefined);
      expect(wrapper.emitted('verified')).toHaveLength(1);
      expect(useSessionStore().session?.recent_auth_until).toBe('2035-11-15T11:30:00Z');
      expect((wrapper.get('[aria-label="当前管理员密码"]').element as HTMLInputElement).value).toBe('');
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    } finally { wrapper.unmount(); }
  });

  it('requires both password and authenticator code for a bound administrator', async () => {
    vi.spyOn(authApi, 'stepUp').mockResolvedValue({ recent_auth_until: '2035-11-15T11:30:00Z' });
    const wrapper = await openDialog(true);
    try {
      await wrapper.get('[aria-label="当前管理员密码"]').setValue('fixture-password');
      await wrapper.get('form').trigger('submit');
      await flushPromises();
      expect(authApi.stepUp).not.toHaveBeenCalled();
      expect(wrapper.get('[role="alert"]').text()).toContain('动态验证码');
      await wrapper.get('[aria-label="当前动态验证码"]').setValue(' 123456 ');
      await wrapper.get('form').trigger('submit');
      await flushPromises();
      expect(authApi.stepUp).toHaveBeenCalledWith('fixture-password', '123456');
      expect(wrapper.emitted('verified')).toHaveLength(1);
      expect((wrapper.get('[aria-label="当前动态验证码"]').element as HTMLInputElement).value).toBe('');
    } finally { wrapper.unmount(); }
  });

  it('clears credentials after rejection without displaying server exception text', async () => {
    vi.spyOn(authApi, 'stepUp').mockRejectedValue(new Error('fixture-sensitive-diagnostic'));
    const wrapper = await openDialog(true);
    try {
      await wrapper.get('[aria-label="当前管理员密码"]').setValue('fixture-password');
      await wrapper.get('[aria-label="当前动态验证码"]').setValue('123456');
      await wrapper.get('form').trigger('submit');
      await flushPromises();
      expect(wrapper.emitted('verified')).toBeUndefined();
      expect(wrapper.get('[role="alert"]').text()).toContain('身份验证失败');
      expect(wrapper.text()).not.toContain('fixture-sensitive-diagnostic');
      expect((wrapper.get('[aria-label="当前管理员密码"]').element as HTMLInputElement).value).toBe('');
      expect((wrapper.get('[aria-label="当前动态验证码"]').element as HTMLInputElement).value).toBe('');
    } finally { wrapper.unmount(); }
  });

  it('never submits while session status is unknown and keeps failed reads closed', async () => {
    const read = deferred<AdminSession>();
    vi.spyOn(authApi, 'session').mockReturnValue(read.promise);
    vi.spyOn(authApi, 'stepUp');
    const wrapper = mount(StepUpDialog, { props: { open: true }, attachTo: document.body });
    try {
      await wrapper.get('form').trigger('submit');
      expect(authApi.stepUp).not.toHaveBeenCalled();
      read.resolve({ ...sessionFixture(), authenticated: false });
      await flushPromises();
      expect(wrapper.get('[role="alert"]').text()).toContain('重新登录');
      await wrapper.get('form').trigger('submit');
      expect(authApi.stepUp).not.toHaveBeenCalled();
    } finally { wrapper.unmount(); }
  });

  it('prevents duplicate submissions and ignores a successful response after cancellation', async () => {
    const pending = deferred<{ recent_auth_until: string }>();
    vi.spyOn(authApi, 'stepUp').mockReturnValue(pending.promise);
    const wrapper = await openDialog();
    try {
      await wrapper.get('[aria-label="当前管理员密码"]').setValue('fixture-password');
      await wrapper.get('form').trigger('submit');
      await wrapper.get('form').trigger('submit');
      expect(authApi.stepUp).toHaveBeenCalledTimes(1);
      await wrapper.get('[data-testid="step-up-cancel"]').trigger('click');
      expect(wrapper.emitted('close')).toHaveLength(1);
      expect((wrapper.get('[aria-label="当前管理员密码"]').element as HTMLInputElement).value).toBe('');
      await wrapper.setProps({ open: false });
      await wrapper.setProps({ open: true });
      await flushPromises();
      pending.resolve({ recent_auth_until: '2035-11-15T11:30:00Z' });
      await flushPromises();
      expect(wrapper.emitted('verified')).toBeUndefined();
      expect((wrapper.get('[aria-label="当前管理员密码"]').element as HTMLInputElement).value).toBe('');
    } finally { wrapper.unmount(); }
  });

  it('ignores a successful response after component disposal', async () => {
    const pending = deferred<{ recent_auth_until: string }>();
    vi.spyOn(authApi, 'stepUp').mockReturnValue(pending.promise);
    const wrapper = await openDialog();
    await wrapper.get('[aria-label="当前管理员密码"]').setValue('fixture-password');
    await wrapper.get('form').trigger('submit');
    wrapper.unmount();
    pending.resolve({ recent_auth_until: '2035-11-15T11:30:00Z' });
    await flushPromises();
    expect(wrapper.emitted('verified')).toBeUndefined();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('clears input on a global unauthorized response and ignores a delayed verification', async () => {
    const pending = deferred<{ recent_auth_until: string }>();
    vi.spyOn(authApi, 'stepUp').mockReturnValue(pending.promise);
    const wrapper = await openDialog(true);
    try {
      const password = wrapper.get('[aria-label="当前管理员密码"]');
      const code = wrapper.get('[aria-label="当前动态验证码"]');
      await password.setValue('fixture-password');
      await code.setValue('123456');
      await wrapper.get('form').trigger('submit');
      vi.stubGlobal('fetch', vi.fn(async () => new Response(
        JSON.stringify({ code: 'UNAUTHENTICATED', message: 'fixture denied' }),
        { status: 401, headers: { 'Content-Type': 'application/json' } },
      )));
      await expect(apiRequest('/api/v1/system')).rejects.toMatchObject({ status: 401 });
      await flushPromises();
      expect((password.element as HTMLInputElement).value).toBe('');
      expect(wrapper.find('[aria-label="当前动态验证码"]').exists()).toBe(false);
      expect(wrapper.emitted('close')).toHaveLength(1);
      pending.resolve({ recent_auth_until: '2035-11-15T11:30:00Z' });
      await flushPromises();
      expect(wrapper.emitted('verified')).toBeUndefined();
      await wrapper.setProps({ open: false });
      await wrapper.setProps({ open: true });
      await flushPromises();
      expect((wrapper.get('[aria-label="当前动态验证码"]').element as HTMLInputElement).value).toBe('');
    } finally { wrapper.unmount(); }
  });

  it('invalidates a delayed session read during global clearing and unregisters on disposal', async () => {
    const pending = deferred<AdminSession>();
    vi.spyOn(authApi, 'session').mockReturnValue(pending.promise);
    vi.spyOn(authApi, 'stepUp');
    const close = vi.fn();
    const wrapper = mount(StepUpDialog, { props: { open: true, onClose: close }, attachTo: document.body });
    clearSensitiveState();
    await flushPromises();
    expect(close).toHaveBeenCalledTimes(1);
    pending.resolve(sessionFixture());
    await flushPromises();
    expect(wrapper.get('[aria-label="当前管理员密码"]').attributes('disabled')).toBeDefined();
    await wrapper.get('form').trigger('submit');
    expect(authApi.stepUp).not.toHaveBeenCalled();
    wrapper.unmount();
    clearSensitiveState();
    expect(close).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted('verified')).toBeUndefined();
  });
});
