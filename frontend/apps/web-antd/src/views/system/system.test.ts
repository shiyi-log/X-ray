import { flushPromises, mount } from '@vue/test-utils';

import { resourcesApi, type SystemInfo } from '@/api/resources';

import SystemSettings from './index.vue';

const systemInfo: SystemInfo = {
  version: '0.12.1',
  environment: 'test',
  debug: false,
  allowed_hosts: ['localhost'],
  csrf_trusted_origins: [],
  provider_identity_network: { enabled: false, source: 'ENVIRONMENT' },
  node_status_sync: {
    enabled: false,
    interval_minutes: 60,
    last_scheduled_at: null,
    source: 'DEFAULT',
  },
};

function mountSystemSettings() {
  return mount(SystemSettings, {
    attachTo: document.body,
    global: { stubs: { transition: false, 'transition-group': false } },
  });
}

describe('system provider identity network setting', () => {
  it('loads the effective value and source, then saves a toggle while disabling the control', async () => {
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
    let resolveUpdate!: (value: SystemInfo) => void;
    const update = vi.spyOn(resourcesApi, 'updateSystem').mockImplementation(
      () => new Promise((resolve) => { resolveUpdate = resolve; }),
    );
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      expect(wrapper.text()).toContain('环境变量默认值');
      expect(wrapper.text()).toContain('否');
      expect(wrapper.text()).toContain('不授予云资源写入权限');
      expect(wrapper.text()).toContain('重复时间');
      expect((wrapper.get('input[aria-label="同步重复时间（分钟）"]').element as HTMLInputElement).value).toBe('60');

      const toggle = wrapper.get('[role="switch"]');
      expect(toggle.attributes('aria-checked')).toBe('false');
      await toggle.trigger('click');
      await vi.waitFor(() => expect(update).toHaveBeenCalledWith({
        provider_identity_network_enabled: true,
      }));
      expect(wrapper.get('[role="switch"]').attributes('disabled')).toBeDefined();

      resolveUpdate({
        ...systemInfo,
        provider_identity_network: { enabled: true, source: 'DATABASE' },
      });
      await flushPromises();
      expect(wrapper.text()).toContain('数据库设置');
      expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('true');
      expect(wrapper.get('[role="switch"]').attributes('disabled')).toBeUndefined();
    } finally {
      wrapper.unmount();
    }
  });

  it('saves the recurring node status interval in minutes', async () => {
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
    const update = vi.spyOn(resourcesApi, 'updateSystem').mockResolvedValue({
      ...systemInfo,
      node_status_sync: { ...systemInfo.node_status_sync, interval_minutes: 30 },
    });
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      const intervalInput = wrapper.get('input[aria-label="同步重复时间（分钟）"]');
      await intervalInput.setValue('30');
      await wrapper.findAll('button').find((button) => button.text().includes('保存间隔'))!.trigger('click');
      await flushPromises();
      expect(update).toHaveBeenCalledWith({ node_status_sync_interval_minutes: 30 });
    } finally {
      wrapper.unmount();
    }
  });

  it('keeps the last effective value and shows an error when saving fails', async () => {
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
    vi.spyOn(resourcesApi, 'updateSystem').mockRejectedValue(new Error('设置保存失败'));
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      await wrapper.get('[role="switch"]').trigger('click');
      await flushPromises();

      expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('false');
      expect(wrapper.get('[role="alert"]').text()).toContain('设置保存失败');
    } finally {
      wrapper.unmount();
    }
  });

  it('shows the normal page error state without exposing an active toggle after load failure', async () => {
    vi.spyOn(resourcesApi, 'system').mockRejectedValue(new Error('系统设置加载失败'));
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      expect(wrapper.get('[role="alert"]').text()).toContain('系统设置加载失败');
      expect(wrapper.find('[role="switch"]').exists()).toBe(false);
    } finally {
      wrapper.unmount();
    }
  });
});
