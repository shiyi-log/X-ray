import { flushPromises, mount } from '@vue/test-utils';
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
