import { DOMWrapper, flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';

import { resetCsrfToken } from '@/api/request';
import { resourcesApi } from '@/api/resources';
import SubscriptionEditor from './SubscriptionEditor.vue';

function fixtureMocks() {
  vi.spyOn(resourcesApi, 'createAccessProfile').mockResolvedValue({ id: 'profile', name: 'phone', status: 'ACTIVE', publishing_frozen: false });
  vi.spyOn(resourcesApi, 'issueSubscription').mockResolvedValue({ subscription_id: 'subscription', token: 'fixture-token', url: 'http://example.test/s/fixture-token', display_once: true });
}

describe('subscription editor', () => {
  it('creates a name-only subscription and delivers a server-generated token', async () => {
    fixtureMocks();
    const wrapper = mount(SubscriptionEditor, { props: { open: false }, attachTo: document.body });
    try {
      await wrapper.setProps({ open: true });
      await flushPromises();
      const dialog = document.querySelector('[role="dialog"]')!;
      const input = dialog.querySelector<HTMLInputElement>('input[id$="name"]') || dialog.querySelector<HTMLInputElement>('input')!;
      input.value = 'phone'; input.dispatchEvent(new Event('input', { bubbles: true }));
      dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await vi.waitFor(() => expect(resourcesApi.issueSubscription).toHaveBeenCalledTimes(1));
      expect(resourcesApi.createAccessProfile).toHaveBeenCalledWith({ name: 'phone' }, expect.any(String));
      expect(resourcesApi.issueSubscription).toHaveBeenCalledWith('profile');
      expect(wrapper.emitted('delivery')).toHaveLength(1);
      expect(wrapper.emitted('saved')).toHaveLength(1);
      expect(wrapper.text()).not.toContain('套餐管理');
      expect(wrapper.text()).not.toContain('节点协议');
      expect(localStorage.length).toBe(0);
    } finally { wrapper.unmount(); }
  });

  it('preserves a created profile after issuance fails so retry cannot duplicate it', async () => {
    fixtureMocks();
    vi.mocked(resourcesApi.issueSubscription).mockRejectedValueOnce(new Error('recent authentication required'));
    const wrapper = mount(SubscriptionEditor, { props: { open: false }, attachTo: document.body });
    try {
      await wrapper.setProps({ open: true }); await flushPromises();
      const dialog = document.querySelector('[role="dialog"]')!;
      const input = dialog.querySelector<HTMLInputElement>('input')!;
      input.value = 'phone'; input.dispatchEvent(new Event('input', { bubbles: true }));
      const submit = () => dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      submit();
      await vi.waitFor(() => expect(dialog.textContent).toContain('recent authentication required'));
      vi.spyOn(resourcesApi, 'updateAccessProfile').mockResolvedValue({ id: 'profile', name: 'phone', status: 'ACTIVE', publishing_frozen: false });
      submit();
      await vi.waitFor(() => expect(wrapper.emitted('saved')).toHaveLength(1));
      expect(resourcesApi.createAccessProfile).toHaveBeenCalledTimes(1);
      expect(wrapper.emitted('delivery')).toHaveLength(1);
    } finally { wrapper.unmount(); }
  });
});

describe('subscription editor identity recovery', () => {
  beforeEach(() => resetCsrfToken());
  afterEach(() => vi.unstubAllGlobals());

  function requestsFixture(errorCode = 'STEP_UP_REQUIRED') {
    const writes: { path: string; method: string; body: unknown }[] = [];
    let verified = false;
    const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
      status, headers: { 'Content-Type': 'application/json' },
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith('/csrf')) return response({ csrf_token: 'fixture-csrf' });
      if (path.endsWith('/session')) return response({
        authenticated: true, mfa_required: false, mfa_enabled: false,
        admin: { username: 'fixture-admin' }, expires_at: '2035-11-15T12:00:00Z', recent_auth_until: null,
      });
      writes.push({ path, method: init?.method || 'GET', body: JSON.parse(String(init?.body)) });
      if (path.endsWith('/step-up')) {
        verified = true;
        return response({ recent_auth_until: '2035-11-15T11:30:00Z' });
      }
      if (path.endsWith('/subscription/')) return verified
        ? response({ subscription_id: 'subscription', token: 'fixture-token', url: 'https://example.test/s/fixture-token', display_once: true })
        : response({ code: errorCode, message: 'fixture-issuance-error' }, 403);
      return response({ id: 'profile', name: 'phone', status: 'ACTIVE', publishing_frozen: false });
    }));
    return writes;
  }

  async function openEditor() {
    const wrapper = mount(SubscriptionEditor, {
      props: { open: false }, attachTo: document.body,
      global: { plugins: [createPinia()], stubs: { transition: false, 'transition-group': false } },
    });
    await wrapper.setProps({ open: true });
    await flushPromises();
    const dialog = new DOMWrapper(document.querySelector('[role="dialog"]')!);
    await dialog.get('input').setValue('phone');
    await dialog.get('form').trigger('submit');
    await flushPromises();
    return { wrapper, dialog };
  }

  it('verifies in place and requires an explicit save retry without duplicating the created profile', async () => {
    const writes = requestsFixture();
    const { wrapper, dialog } = await openEditor();
    try {
      const password = document.querySelector<HTMLInputElement>('[aria-label="当前管理员密码"]');
      expect(password, 'issuance rejection must provide in-place verification').not.toBeNull();
      expect(wrapper.emitted('delivery')).toBeUndefined();
      await new DOMWrapper(password!).setValue('fixture-password');
      await new DOMWrapper(password!.closest('form')!).trigger('submit');
      await flushPromises();
      expect(writes.filter((entry) => entry.path.endsWith('/step-up'))).toEqual([
        { path: '/api/v1/auth/step-up', method: 'POST', body: { password: 'fixture-password' } },
      ]);
      expect(writes.filter((entry) => entry.path.endsWith('/subscription/'))).toHaveLength(1);
      expect(wrapper.emitted('saved')).toBeUndefined();
      expect(dialog.text()).toContain('再次保存');
      await dialog.get('form').trigger('submit');
      await flushPromises();
      expect(writes.filter((entry) => entry.path === '/api/v1/access-profiles/')).toHaveLength(1);
      expect(writes.filter((entry) => entry.path.endsWith('/subscription/'))).toHaveLength(2);
      expect(wrapper.emitted('delivery')).toHaveLength(1);
      expect(wrapper.emitted('saved')).toHaveLength(1);
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    } finally { wrapper.unmount(); }
  });

  it('keeps the draft and created profile when verification is cancelled or the editor is closed', async () => {
    const writes = requestsFixture();
    const { wrapper, dialog } = await openEditor();
    try {
      const cancel = document.querySelector('[data-testid="step-up-cancel"]');
      expect(cancel, 'verification must be cancellable').not.toBeNull();
      await new DOMWrapper(cancel!).trigger('click');
      await flushPromises();
      expect((dialog.get('input').element as HTMLInputElement).value).toBe('phone');
      expect(document.querySelector('[aria-label="当前管理员密码"]')).toBeNull();
      await dialog.get('form').trigger('submit');
      await flushPromises();
      expect(writes.filter((entry) => entry.path === '/api/v1/access-profiles/')).toHaveLength(1);
      expect(document.querySelector('[aria-label="当前管理员密码"]')).not.toBeNull();
      await wrapper.setProps({ open: false });
      await flushPromises();
      expect(document.querySelector('[aria-label="当前管理员密码"]')).toBeNull();
      expect(wrapper.emitted('delivery')).toBeUndefined();
    } finally { wrapper.unmount(); }
  });

  it('does not open identity verification for an unrelated forbidden response', async () => {
    requestsFixture('POLICY_DENIED');
    const { wrapper, dialog } = await openEditor();
    try {
      expect(dialog.text()).toContain('fixture-issuance-error');
      expect(document.querySelector('[aria-label="当前管理员密码"]')).toBeNull();
      expect(wrapper.emitted('delivery')).toBeUndefined();
    } finally { wrapper.unmount(); }
  });
});
