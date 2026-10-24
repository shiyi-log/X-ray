import { mount } from '@vue/test-utils';

import { clearSensitiveState } from '@/api/request';

import SecretDelivery from './SecretDelivery.vue';

const delivery = {
  subscription_id: '11111111-1111-4111-8111-111111111111',
  token: 'test-only-token-that-must-remain-in-memory-12345',
  urls: {
    shadowrocket: 'http://example.test/s/token?format=shadowrocket',
    clash: 'http://example.test/s/token?format=clash',
    mihomo: 'http://example.test/s/token?format=mihomo',
    v2ray: 'http://example.test/s/token?format=v2ray',
  },
  display_once: true,
};

describe('SecretDelivery', () => {
  it.each([
    { name: '遮罩', event: 'click', options: {}, closeSelector: '[aria-label="关闭"]' },
    {
      name: 'Esc', event: 'keydown', options: { key: 'Escape', keyCode: 27 },
      closeSelector: '.ant-modal-footer button',
    },
  ])('$name 不会丢弃一次性交付内容，显式关闭才立即清空', async ({ event, options, closeSelector }) => {
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });
    try {
      await wrapper.get('.ant-modal-wrap').trigger(event, options);

      expect(wrapper.emitted('close')).toBeUndefined();
      expect(wrapper.text()).toContain(delivery.token);
      await wrapper.get(closeSelector).trigger('click');

      expect(wrapper.emitted('close')).toHaveLength(1);
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
      expect(wrapper.text()).not.toContain(delivery.token);
      for (const url of Object.values(delivery.urls)) {
        expect(wrapper.text()).not.toContain(url);
      }
    } finally {
      wrapper.unmount();
    }
  });

  it('只显示传入内存内容，复制不会请求新版本', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });

    await wrapper.get('[data-testid="copy-token"]').trigger('click');
    expect(writeText).toHaveBeenCalledWith(delivery.token);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('401/退出触发的敏感清理会立即关闭并清空展示', async () => {
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });
    expect(wrapper.text()).toContain(delivery.token);
    clearSensitiveState();
    await wrapper.vm.$nextTick();

    expect(wrapper.emitted('close')).toHaveLength(1);
    expect(wrapper.text()).not.toContain(delivery.token);
  });
});
