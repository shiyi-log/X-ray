import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';

import { resetCsrfToken } from '@/api/request';
import { useSessionStore } from '@/stores/session';

import SubscriptionList from './index.vue';

const subscription = {
  id: 'subscription-1', pool_id: 'pool', pool_name: 'pool', profile_id: 'profile-1',
  profile_name: 'phone', status: 'ACTIVE', current_token_status: 'ACTIVE', token_epoch: 1,
  current_revision: 1, public_version: 'v1', revision_usable: true, formats: ['mihomo'],
  unavailable_reasons: {}, created_at: '2026-11-06T00:00:00Z', updated_at: '2026-11-06T00:00:00Z',
};
const profile = { id: 'profile-2', name: 'tablet', status: 'ACTIVE', publishing_frozen: false, credential_count: 0, subscription_id: null };
const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 25 });
function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}
function button(root: ReturnType<typeof mount>, text: string) {
  const found = root.findAll('button').find((item) => item.text().replace(/\s/g, '').includes(text));
  expect(found, `missing action: ${text}`).toBeDefined();
  return found!;
}
function mountList() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().applySession({ authenticated: true, mfa_enabled: false, mfa_required: false, admin: { username: 'admin' }, recent_auth_until: null, expires_at: null });
  const router = createRouter({ history: createMemoryHistory(), routes: [] });
  return mount(SubscriptionList, { attachTo: document.body, global: { plugins: [pinia, router], stubs: { transition: false, 'transition-group': false } } });
}

describe('subscription sensitive actions and link entry', () => {
  beforeEach(() => resetCsrfToken());
  afterEach(() => vi.unstubAllGlobals());

  it('offers verification after issuance is rejected and waits for an explicit retry', async () => {
    let verified = false;
    let issuanceWrites = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith('/csrf')) return response({ csrf_token: 'fixture-csrf' });
      if (path.endsWith('/auth/session')) return response({ authenticated: true, mfa_enabled: false, mfa_required: false, admin: { username: 'admin' }, recent_auth_until: null, expires_at: null });
      if (path.endsWith('/step-up')) { verified = true; return response({ recent_auth_until: '2035-01-01T00:00:00Z' }); }
      if (path.endsWith('/subscription/')) {
        issuanceWrites += 1;
        return verified ? response({ subscription_id: 'new', token: 'fixture-token', url: 'https://example.test/s/fixture', display_once: true }) : response({ code: 'STEP_UP_REQUIRED', message: '请重新验证身份' }, 403);
      }
      if (path.startsWith('/api/v1/access-profiles/')) return response(page([profile]));
      return response(page([]));
    }));
    const wrapper = mountList();
    try {
      await flushPromises();
      await button(wrapper, '签发Token').trigger('click');
      await flushPromises();
      expect(issuanceWrites).toBe(1);
      expect(document.querySelector('[aria-label="当前管理员密码"]')).not.toBeNull();
      const password = document.querySelector<HTMLInputElement>('[aria-label="当前管理员密码"]')!;
      password.value = 'test-only-password'; password.dispatchEvent(new Event('input', { bubbles: true }));
      password.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await flushPromises();
      expect(issuanceWrites).toBe(1);
      expect(wrapper.text()).toContain('请再次点击');
      await button(wrapper, '签发Token').trigger('click');
      await flushPromises();
      expect(issuanceWrites).toBe(2);
      expect(wrapper.text()).toContain('复制订阅链接');
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    } finally { wrapper.unmount(); }
  });

  it('requires explicit rotation confirmation from the persistent subscription link entry', async () => {
    let rotations = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith('/csrf')) return response({ csrf_token: 'fixture-csrf' });
      if (path.endsWith('/rotate/')) { rotations += 1; return response({ subscription_id: 'subscription-1', token: 'fixture-token', url: 'https://example.test/s/new', display_once: true }); }
      if (path.startsWith('/api/v1/access-profiles/')) return response(page([]));
      return response(page([subscription]));
    }));
    const wrapper = mountList();
    try {
      await flushPromises();
      await button(wrapper, '订阅链接').trigger('click');
      await flushPromises();
      expect(rotations).toBe(0);
      expect(document.body.textContent).toContain('旧链接将立即失效');
      const confirm = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')).find((el) => el.textContent?.includes('确认轮换并获取新链接'))!;
      expect(confirm).toBeDefined();
      confirm.click();
      await flushPromises();
      expect(rotations).toBe(1);
      expect(wrapper.text()).toContain('复制订阅链接');
      expect(wrapper.text()).toContain('复制小火箭链接');
    } finally { wrapper.unmount(); }
  });
});
