import { DOMWrapper, flushPromises, mount } from '@vue/test-utils';

import {
  resourcesApi,
  SUPPORTED_REGIONS,
  type NodePool,
  type Page,
} from '@/api/resources';

import NodePools from './index.vue';

describe('node pool region allocation', () => {
  it('loads and preserves existing per-region allocations when saving', async () => {
    expect(SUPPORTED_REGIONS).not.toContain('eu-west-1');

    const page: Page<NodePool> = {
      items: [{
        id: 'pool-1', name: 'IP', region: 'ap-southeast-1', quota: 3,
        allow_create: false,
        used: 1, available: 2,
        regions: ['ap-southeast-1', 'eu-west-1'],
        allocations: [
          { region: 'ap-southeast-1', quota: 2, used: 1, available: 1 },
          { region: 'eu-west-1', quota: 2, used: 1, available: 1 },
        ],
      }],
      total: 1,
      page: 1,
      page_size: 20,
    };
    vi.spyOn(resourcesApi, 'nodePools').mockResolvedValue(page);
    const updatePool = vi.spyOn(resourcesApi, 'updateNodePool').mockResolvedValue(page.items[0]!);
    const createPool = vi.spyOn(resourcesApi, 'createNodePool').mockResolvedValue(page.items[0]!);
    const wrapper = mount(NodePools, {
      attachTo: document.body,
      global: { stubs: { transition: false, 'transition-group': false } },
    });

    try {
      await flushPromises();
      expect(wrapper.text()).toContain('ap-southeast-1、eu-west-1');
      expect(wrapper.text()).not.toContain('总额度');
      expect(wrapper.text()).not.toContain('占用');
      expect(wrapper.text()).not.toContain('可用');
      expect(wrapper.text()).not.toContain('1/2');
      expect(wrapper.text()).not.toContain('0/1');
      expect(wrapper.text()).not.toContain('暂停创建');
      expect(wrapper.text()).toContain('已关闭');
      await wrapper.findAll('button').find((item) => item.text() === '地区分配')!.trigger('click');
      await flushPromises();
      const dialog = new DOMWrapper(document.querySelector('[role="dialog"]')!);
      expect(dialog.text()).toContain('地区分配');
      expect(dialog.text()).toContain('eu-west-1（历史地区）');
      expect(dialog.text()).not.toContain('名称');
      expect((dialog.get('[aria-label="允许创建服务器"]').element as HTMLButtonElement).getAttribute('aria-checked')).toBe('false');
      await dialog.get('form').trigger('submit');
      await vi.waitFor(() => expect(updatePool).toHaveBeenCalledTimes(1));
      expect(updatePool).toHaveBeenCalledWith('pool-1', {
        allocations: [
          { region: 'ap-southeast-1', quota: 2 },
          { region: 'eu-west-1', quota: 2 },
        ],
        allow_create: false,
      });
      expect(createPool).not.toHaveBeenCalled();
    } finally {
      wrapper.unmount();
    }
  });

  it('creates the single pool only when no configuration exists', async () => {
    const emptyPage: Page<NodePool> = { items: [], total: 0, page: 1, page_size: 20 };
    vi.spyOn(resourcesApi, 'nodePools').mockResolvedValue(emptyPage);
    const createPool = vi.spyOn(resourcesApi, 'createNodePool').mockResolvedValue({
      id: 'pool-1', name: 'IP', region: 'ap-southeast-1', quota: 3,
      allow_create: false,
      used: 0, available: 3,
      regions: ['ap-southeast-1'],
      allocations: [{ region: 'ap-southeast-1', quota: 3, used: 0, available: 3 }],
    });
    const updatePool = vi.spyOn(resourcesApi, 'updateNodePool');
    const wrapper = mount(NodePools, {
      attachTo: document.body,
      global: { stubs: { transition: false, 'transition-group': false } },
    });

    try {
      await flushPromises();
      await wrapper.findAll('button').find((item) => item.text() === '地区分配')!.trigger('click');
      await flushPromises();
      const dialog = new DOMWrapper(document.querySelector('[role="dialog"]')!);
      await dialog.get('[aria-label="允许创建服务器"]').trigger('click');
      await dialog.get('form').trigger('submit');
      await vi.waitFor(() => expect(createPool).toHaveBeenCalledTimes(1));
      expect(createPool).toHaveBeenCalledWith({
        allocations: [{ region: 'ap-southeast-1', quota: 3 }],
        allow_create: false,
      });
      expect(updatePool).not.toHaveBeenCalled();
    } finally {
      wrapper.unmount();
    }
  });
});
