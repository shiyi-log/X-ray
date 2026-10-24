import { flushPromises, mount } from '@vue/test-utils';
import { resourcesApi } from '@/api/resources';
import SubscriptionEditor from './SubscriptionEditor.vue';

function fixtureMocks() {
  vi.spyOn(resourcesApi, 'subscriptionPlans').mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
  vi.spyOn(resourcesApi, 'subscriptionCatalog').mockResolvedValue({ items: [] });
  vi.spyOn(resourcesApi, 'createAccessProfile').mockResolvedValue({ id: 'profile', name: 'phone', status: 'ACTIVE', publishing_frozen: false });
  vi.spyOn(resourcesApi, 'issueSubscription').mockResolvedValue({ subscription_id: 'subscription', token: 'fixture-token', urls: {}, display_once: true });
  vi.spyOn(resourcesApi, 'assignSubscription').mockResolvedValue({ operation_ids: [], pending: false });
}

describe('subscription editor', () => {
  it('creates a profile, delivers once and assigns only selected protocols', async () => {
    fixtureMocks();
    const wrapper = mount(SubscriptionEditor, { props: { open: false }, attachTo: document.body });
    try {
      await wrapper.setProps({ open: true });
      await flushPromises();
      const dialog = document.querySelector('[role="dialog"]')!;
      const input = dialog.querySelector<HTMLInputElement>('input[id$="name"]') || dialog.querySelector<HTMLInputElement>('input')!;
      input.value = 'phone'; input.dispatchEvent(new Event('input', { bubbles: true }));
      dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await vi.waitFor(() => expect(resourcesApi.assignSubscription).toHaveBeenCalledTimes(1));
      expect(resourcesApi.issueSubscription).toHaveBeenCalledWith('profile');
      expect(resourcesApi.assignSubscription).toHaveBeenCalledWith('subscription', [], expect.any(String));
      expect(wrapper.emitted('delivery')).toHaveLength(1);
      expect(wrapper.emitted('saved')).toHaveLength(1);
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
