import { flushPromises, mount } from '@vue/test-utils';

import { clearSensitiveState } from '@/api/request';

import SecretDelivery from './SecretDelivery.vue';

const delivery = {
  subscription_id: '11111111-1111-4111-8111-111111111111',
  token: 'test-only-token-that-must-remain-in-memory-12345',
  url: 'http://example.test/s/token',
  display_once: true,
};

describe('SecretDelivery', () => {
  afterEach(() => vi.useRealTimers());

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
      expect(wrapper.text()).not.toContain(delivery.url);
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

    try {
      await wrapper.get('[data-testid="copy-token"]').trigger('click');
      expect(writeText).toHaveBeenCalledWith(delivery.token);
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    } finally {
      wrapper.unmount();
    }
  });

  it('展示统一订阅链接与可手动复制的小火箭格式链接', () => {
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });

    try {
      expect(wrapper.get('[data-testid="unified-url"]').text()).toBe(delivery.url);
      expect(wrapper.text()).toContain('包含所有已发布且受支持的协议');
      expect(wrapper.get('[data-testid="shadowrocket-url"]').text()).toBe('http://example.test/s/token?format=shadowrocket');
      expect(wrapper.findAll('[data-testid="unified-url"]')).toHaveLength(1);
    } finally {
      wrapper.unmount();
    }
  });

  it('通过可见文字入口复制完整统一链接，不发请求或保存到浏览器存储', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });
    try {
      const button = wrapper.findAll('button').find((item) => item.text().includes('复制订阅链接'));
      expect(button, '交付弹窗应有可见的链接复制文字').toBeDefined();
      await button!.trigger('click');
      await flushPromises();
      expect(writeText).toHaveBeenCalledExactlyOnceWith('http://example.test/s/token');
      expect(button!.text()).toContain('已复制');
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    } finally { wrapper.unmount(); }
  });

  it('复制小火箭格式时替换格式参数并保留其他参数', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery: { ...delivery, url: 'https://example.test/s/fixture?format=mihomo&client=phone' } } });
    try {
      const button = wrapper.findAll('button').find((item) => item.text().includes('复制小火箭链接'));
      expect(button, '交付弹窗应有明确的小火箭复制入口').toBeDefined();
      await button!.trigger('click');
      await flushPromises();
      expect(writeText).toHaveBeenCalledExactlyOnceWith('https://example.test/s/fixture?format=shadowrocket&client=phone');
      expect(wrapper.get('[data-testid="unified-url"]').text()).toBe('https://example.test/s/fixture?format=mihomo&client=phone');
      expect(button!.text()).toContain('已复制');
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    } finally { wrapper.unmount(); }
  });

  it('复制失败保留对应完整链接供手动复制，且不显示复制成功', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(async () => { throw new Error('fixture clipboard denied'); }) } });
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });
    try {
      const button = wrapper.findAll('button').find((item) => item.text().includes('复制小火箭链接'));
      expect(button).toBeDefined();
      await button!.trigger('click');
      await flushPromises();
      expect(wrapper.text()).toContain('剪贴板不可用，请手动复制订阅链接');
      expect(wrapper.get('[data-testid="shadowrocket-url"]').text()).toBe('http://example.test/s/token?format=shadowrocket');
      expect(wrapper.text()).not.toContain('fixture clipboard denied');
      expect(button!.text()).not.toContain('已复制');
    } finally { wrapper.unmount(); }
  });

  it.each(['success', 'failure'] as const)('旧交付的延迟复制 %s 不影响关闭后打开的新交付', async (outcome) => {
    let resolveCopy!: () => void;
    let rejectCopy!: (error: Error) => void;
    const pending = new Promise<void>((resolve, reject) => { resolveCopy = resolve; rejectCopy = reject; });
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(() => pending) } });
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });
    try {
      await wrapper.get('[aria-label="复制统一订阅链接"]').trigger('click');
      await wrapper.get('[aria-label="关闭"]').trigger('click');
      await wrapper.setProps({ open: false, delivery: null });
      await wrapper.setProps({ open: true, delivery: { ...delivery, token: 'fixture-new-token', url: 'https://example.test/s/new' } });
      if (outcome === 'success') resolveCopy();
      else rejectCopy(new Error('fixture stale clipboard denied'));
      await flushPromises();
      expect(wrapper.get('[data-testid="unified-url"]').text()).toBe('https://example.test/s/new');
      expect(wrapper.get('[aria-label="复制统一订阅链接"]').text()).toContain('复制订阅链接');
      expect(wrapper.text()).not.toContain('已复制');
      expect(wrapper.text()).not.toContain('剪贴板不可用');
    } finally { wrapper.unmount(); }
  });

  it('旧交付的反馈定时器不会提前清除新交付的复制成功提示', async () => {
    vi.useFakeTimers();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(async () => undefined) } });
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });
    try {
      await wrapper.get('[aria-label="复制统一订阅链接"]').trigger('click');
      await vi.advanceTimersByTimeAsync(1_000);
      await wrapper.get('[aria-label="关闭"]').trigger('click');
      await wrapper.setProps({ open: false, delivery: null });
      await wrapper.setProps({ open: true, delivery: { ...delivery, url: 'https://example.test/s/new' } });
      await wrapper.get('[aria-label="复制统一订阅链接"]').trigger('click');
      await vi.advanceTimersByTimeAsync(600);
      expect(wrapper.get('[aria-label="复制统一订阅链接"]').text()).toContain('已复制');
      await vi.advanceTimersByTimeAsync(999);
      expect(wrapper.get('[aria-label="复制统一订阅链接"]').text()).toContain('已复制');
      await vi.advanceTimersByTimeAsync(1);
      expect(wrapper.get('[aria-label="复制统一订阅链接"]').text()).toContain('复制订阅链接');
    } finally { wrapper.unmount(); }
  });

  it('交付五分钟边界立即清除两种链接，卸载后不再触发关闭', async () => {
    vi.useFakeTimers();
    const wrapper = mount(SecretDelivery, { props: { open: true, delivery } });
    try {
      await vi.advanceTimersByTimeAsync(299_999);
      expect(wrapper.find('[data-testid="unified-url"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="shadowrocket-url"]').exists()).toBe(true);
      await vi.advanceTimersByTimeAsync(1);
      expect(wrapper.emitted('close')).toHaveLength(1);
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
      expect(wrapper.text()).not.toContain(delivery.token);
      expect(wrapper.text()).not.toContain(delivery.url);
      await vi.advanceTimersByTimeAsync(1);
      expect(wrapper.emitted('close')).toHaveLength(1);
    } finally { wrapper.unmount(); }
    const unmounted = mount(SecretDelivery, { props: { open: true, delivery } });
    unmounted.unmount();
    await vi.advanceTimersByTimeAsync(300_000);
    expect(unmounted.emitted('close')).toBeUndefined();
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
