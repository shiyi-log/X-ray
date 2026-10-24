import { DOMWrapper, flushPromises, mount } from '@vue/test-utils';

import {
  resourcesApi,
  SUPPORTED_REGIONS,
  type NodePool,
  type Page,
} from '@/api/resources';

import NodePools from './index.vue';

function inputFor(dialog: DOMWrapper<Element>, labelText: string) {
  const label = [...dialog.element.querySelectorAll('label')].find(
    (item) => item.textContent === labelText,
  );
  expect(label, `missing label ${labelText}`).toBeDefined();
  return dialog.get<HTMLInputElement>(`input[id="${label!.htmlFor}"]`);
}

describe('node pool region allocation', () => {
  it('shows per-region allocation and submits multiple preset regions', async () => {
    expect(SUPPORTED_REGIONS).not.toContain('eu-west-1');

    const page: Page<NodePool> = {
      items: [{
        id: 'pool-1', name: '新加坡池', region: 'ap-southeast-1', quota: 3,
        used: 1, available: 2, allow_create: true,
        regions: ['ap-southeast-1', 'ap-northeast-1'],
        allocations: [
          { region: 'ap-southeast-1', quota: 2, used: 1, available: 1 },
          { region: 'ap-northeast-1', quota: 1, used: 0, available: 1 },
        ],
      }],
      total: 1,
      page: 1,
      page_size: 20,
    };
    vi.spyOn(resourcesApi, 'nodePools').mockResolvedValue(page);
    let submitted: { name: string; allocations: { region: string; quota: number }[] } | undefined;
    const createPool = vi.spyOn(resourcesApi, 'createNodePool').mockImplementation(async (payload) => {
      submitted = { ...payload, allocations: payload.allocations.map((item) => ({ ...item })) };
      return page.items[0]!;
    });
    const wrapper = mount(NodePools, {
      attachTo: document.body,
      global: { stubs: { transition: false, 'transition-group': false } },
    });

    try {
      await flushPromises();
      expect(wrapper.text()).toContain('ap-southeast-1：1/2');
      expect(wrapper.text()).toContain('ap-northeast-1：0/1');
      await wrapper.findAll('button').find((item) => item.text() === '新建节点池')!.trigger('click');
      await flushPromises();
      const dialog = new DOMWrapper(document.querySelector('[role="dialog"]')!);
      await inputFor(dialog, '名称').setValue('多地区池');
      await dialog.findAll('button').find((item) => item.text() === '添加地区')!.trigger('click');
      await dialog.get('form').trigger('submit');
      await vi.waitFor(() => expect(createPool).toHaveBeenCalledTimes(1));
      expect(submitted).toEqual({
        name: '多地区池',
        allocations: [
          { region: 'ap-southeast-1', quota: 3 },
          { region: 'ap-northeast-1', quota: 1 },
        ],
      });
    } finally {
      wrapper.unmount();
    }
  });
});
