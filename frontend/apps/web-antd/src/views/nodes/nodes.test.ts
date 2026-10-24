import { createMemoryHistory, createRouter } from 'vue-router';
import { flushPromises, mount } from '@vue/test-utils';

import { resourcesApi, type ManagedNode } from '@/api/resources';

import Nodes from './index.vue';

describe('nodes table labels', () => {
  it('renders translated platform, statuses and generation heading', async () => {
    vi.spyOn(resourcesApi, 'nodes').mockResolvedValue({
      items: [{
        id: 'node-1',
        name: '新加坡节点',
        provider: 'aws_lightsail',
        region: 'ap-southeast-1',
        raw_cloud_state: 'PENDING',
        provisioning_state: 'DELETED',
        health_state: 'UNKNOWN',
        security_state: 'OPEN',
        pool_id: 'pool-1',
        applied_generation: 2,
        desired_generation: 3,
      } as ManagedNode],
      total: 1,
      page: 1,
      page_size: 20,
    });
    const router = createRouter({ history: createMemoryHistory(), routes: [] });
    const wrapper = mount(Nodes, {
      attachTo: document.body,
      global: { plugins: [router], stubs: { transition: false, 'transition-group': false } },
    });

    try {
      await flushPromises();
      const text = wrapper.text();
      expect(text).toContain('AWS Lightsail');
      expect(text).toContain('待处理');
      expect(text).toContain('已删除');
      expect(text).toContain('未知');
      expect(text).toContain('开放');
      expect(text).toContain('配置代次');
      expect(text).not.toContain('aws_lightsail');
      expect(text).not.toContain('Generation');
    } finally {
      wrapper.unmount();
    }
  });
});
