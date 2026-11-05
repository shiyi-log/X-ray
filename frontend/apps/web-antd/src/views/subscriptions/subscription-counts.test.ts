import { flushPromises, mount } from '@vue/test-utils';

import { resourcesApi, type AccessProfile, type Subscription } from '@/api/resources';

import SubscriptionList from './index.vue';

describe('subscription node count reconciliation', () => {
  it('shows expected, assigned, ready, published counts and flags drift', async () => {
    const subscription: Subscription = {
      id: 'subscription-1',
      pool_id: 'pool-1',
      pool_name: 'Singapore',
      profile_id: 'profile-1',
      profile_name: 'phone',
      status: 'ACTIVE',
      current_token_status: 'ACTIVE',
      token_epoch: 1,
      current_revision: 2,
      public_version: 'v2',
      revision_usable: true,
      node_counts: {
        expected: 3,
        assigned: 2,
        ready: 2,
        published: 1,
        mismatch: true,
      },
      formats: ['mihomo'],
      unavailable_reasons: {},
      created_at: '2026-11-06T00:00:00Z',
      updated_at: '2026-11-06T00:00:00Z',
    };
    vi.spyOn(resourcesApi, 'subscriptions').mockResolvedValue({
      items: [subscription],
      total: 1,
      page: 1,
      page_size: 25,
    });
    vi.spyOn(resourcesApi, 'accessProfiles').mockResolvedValue({
      items: [] as AccessProfile[],
      total: 0,
      page: 1,
      page_size: 25,
    });

    const wrapper = mount(SubscriptionList, { attachTo: document.body });
    try {
      await flushPromises();
      expect(wrapper.text()).toContain('已分配 2 / 3');
      expect(wrapper.text()).toContain('健康 2');
      expect(wrapper.text()).toContain('已发布 1');
      expect(wrapper.text()).toContain('节点不匹配');
    } finally {
      wrapper.unmount();
    }
  });
});
