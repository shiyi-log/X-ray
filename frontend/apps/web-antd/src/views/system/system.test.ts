import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

import { resetCsrfToken } from '@/api/request';
import { useSessionStore } from '@/stores/session';

import { resourcesApi, type SystemInfo } from '@/api/resources';

import SystemSettings from './index.vue';

const systemInfo: SystemInfo = {
  version: '0.14.8',
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
  node_pool_sync: {
    enabled: false,
    interval_minutes: 15,
    creation_templates: [],
    last_scheduled_at: null,
    source: 'DEFAULT',
  },
  node_daily_restart: {
    enabled: false,
    time: '04:00',
    timezone: 'Asia/Shanghai',
    last_scheduled_at: null,
    source: 'DEFAULT',
  },
  usage_sync: {
    enabled: true,
    interval_minutes: 1,
    last_scheduled_at: null,
    source: 'DEFAULT',
  },
};

function mountSystemSettings(mfaEnabled = false, recentAuthUntil: string | null = null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().applySession({ authenticated: true, mfa_required: false, mfa_enabled: mfaEnabled, admin: { username: 'admin' }, expires_at: '2035-11-08T16:00:00Z', recent_auth_until: recentAuthUntil });
  return mount(SystemSettings, {
    attachTo: document.body,
    global: { plugins: [pinia], stubs: { transition: false, 'transition-group': false } },
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

describe('node automation settings', () => {
  it('keeps the template form and list unchanged when adding a template fails', async () => {
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
    vi.spyOn(resourcesApi, 'updateSystem').mockRejectedValue(new Error('模板保存失败'));
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      await wrapper.get('input[aria-label="创建模板地区"]').setValue('ap-southeast-1');
      await wrapper.get('input[aria-label="创建模板云账号 ID"]').setValue('account-1');
      await wrapper.get('input[aria-label="创建模板套餐 ID"]').setValue('small-plan');
      await wrapper.get('input[aria-label="创建模板镜像 ID"]').setValue('ubuntu-image');
      await wrapper.findAll('button').find((button) => button.text().includes('添加创建模板'))!.trigger('click');
      await flushPromises();

      expect(wrapper.text()).not.toContain('新加坡');
      expect((wrapper.get('input[aria-label="创建模板地区"]').element as HTMLInputElement).value).toBe('ap-southeast-1');
      expect(wrapper.get('[role="alert"]').text()).toContain('模板保存失败');
    } finally {
      wrapper.unmount();
    }
  });

  it('keeps an existing template visible when its removal fails', async () => {
    const existingTemplateInfo: SystemInfo = {
      ...systemInfo,
      node_pool_sync: {
        ...systemInfo.node_pool_sync,
        creation_templates: [{
          region: 'ap-southeast-1',
          cloud_account_id: 'account-1',
          plan_id: 'small-plan',
          image_id: 'ubuntu-image',
        }],
      },
    };
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(existingTemplateInfo);
    vi.spyOn(resourcesApi, 'updateSystem').mockRejectedValue(new Error('模板保存失败'));
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      expect(wrapper.text()).toContain('新加坡');
      await wrapper.findAll('button').find((button) => button.text().includes('删除'))!.trigger('click');
      await flushPromises();

      expect(wrapper.text()).toContain('新加坡');
      expect(wrapper.get('[role="alert"]').text()).toContain('模板保存失败');
    } finally {
      wrapper.unmount();
    }
  });

  it('saves pool alignment interval and an explicit per-region creation template', async () => {
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
    const template = {
      region: 'ap-southeast-1',
      cloud_account_id: 'account-1',
      plan_id: 'small-plan',
      image_id: 'ubuntu-image',
    } satisfies SystemInfo['node_pool_sync']['creation_templates'][number];
    const savedSystemInfo: SystemInfo = {
      ...systemInfo,
      node_pool_sync: {
        ...systemInfo.node_pool_sync,
        creation_templates: [template],
      },
    };
    const update = vi.spyOn(resourcesApi, 'updateSystem')
      .mockResolvedValueOnce(systemInfo)
      .mockResolvedValueOnce(savedSystemInfo);
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      await wrapper.get('input[aria-label="地址池同步间隔（分钟）"]').setValue('30');
      await wrapper.findAll('button').find((button) => button.text().includes('保存地址池间隔'))!.trigger('click');
      await flushPromises();
      expect(update).toHaveBeenCalledWith({ node_pool_sync_interval_minutes: 30 });

      await wrapper.get('input[aria-label="创建模板地区"]').setValue('ap-southeast-1');
      await wrapper.get('input[aria-label="创建模板云账号 ID"]').setValue('account-1');
      await wrapper.get('input[aria-label="创建模板套餐 ID"]').setValue('small-plan');
      await wrapper.get('input[aria-label="创建模板镜像 ID"]').setValue('ubuntu-image');
      await wrapper.findAll('button').find((button) => button.text().includes('添加创建模板'))!.trigger('click');
      await flushPromises();

      expect(update).toHaveBeenLastCalledWith({
        node_pool_sync_creation_templates: [template],
      });
      expect(wrapper.text()).toContain('新加坡');
    } finally {
      wrapper.unmount();
    }
  });

  it('saves the daily restart local time and timezone', async () => {
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
    const update = vi.spyOn(resourcesApi, 'updateSystem').mockResolvedValue(systemInfo);
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      await wrapper.get('input[aria-label="每日重启时间"]').setValue('05:30');
      await wrapper.get('input[aria-label="每日重启时区"]').setValue('America/New_York');
      await wrapper.findAll('button').find((button) => button.text().includes('保存重启计划'))!.trigger('click');
      await flushPromises();
      expect(update).toHaveBeenCalledWith({
        node_daily_restart_time: '05:30',
        node_daily_restart_timezone: 'America/New_York',
      });
    } finally {
      wrapper.unmount();
    }
  });

  it('saves the scheduled traffic and subscription usage sync interval', async () => {
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
    const update = vi.spyOn(resourcesApi, 'updateSystem').mockResolvedValue(systemInfo);
    const wrapper = mountSystemSettings();

    try {
      await flushPromises();
      await wrapper.get('input[aria-label="流量同步间隔（分钟）"]').setValue('10');
      await wrapper.findAll('button').find((button) => button.text().includes('保存流量间隔'))!.trigger('click');
      await flushPromises();
      expect(update).toHaveBeenCalledWith({ usage_sync_interval_minutes: 10 });
    } finally {
      wrapper.unmount();
    }
  });
});


describe('optional administrator authenticator', () => {
  const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
  beforeEach(() => {
    resetCsrfToken();
    requests.length = 0;
    vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      let body: unknown;
      if (path.endsWith('/csrf')) body = { csrf_token: 'csrf' };
      else {
        const payload = JSON.parse(String(init?.body || '{}')) as Record<string, unknown>;
        requests.push({ path, body: payload });
        if (path.endsWith('/step-up')) body = { recent_auth_until: '2035-11-08T15:30:00Z' };
        else if (path.endsWith('/totp/setup')) body = { challenge_id: '11111111-1111-4111-8111-111111111111', secret: 'test-only-enrollment-key', otpauth_uri: '', expires_at: '2035-11-08T15:30:00Z' };
        else if (path.endsWith('/totp/confirm')) body = { authenticated: true, mfa_required: false, mfa_enabled: true, admin: { username: 'admin' }, expires_at: '2035-11-08T16:00:00Z', recent_auth_until: '2035-11-08T15:30:00Z', recovery_codes: ['test-only-recovery-code'] };
        else throw new Error('Unexpected authentication request');
      }
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('does not force enrollment, verifies an unbound admin with password only, and clears the password', async () => {
    const wrapper = mountSystemSettings();
    try {
      await flushPromises();
      expect(wrapper.text()).toContain('未绑定验证器，使用密码登录');
      expect(wrapper.find('input[aria-label="当前动态验证码"]').exists()).toBe(false);
      expect(requests).toEqual([]);
      await wrapper.get('input[aria-label="当前管理员密码"]').setValue('test-only-password');
      await wrapper.get('[data-testid="identity-step-up"]').trigger('submit');
      await flushPromises();
      expect(requests).toEqual([{ path: '/api/v1/auth/step-up', body: { password: 'test-only-password' } }]);
      expect((wrapper.get('input[aria-label="当前管理员密码"]').element as HTMLInputElement).value).toBe('');
      expect(wrapper.get('[data-testid="begin-optional-totp"]').attributes('disabled')).toBeUndefined();
      expect(useSessionStore().session?.recent_auth_until).toBe('2035-11-08T15:30:00Z');
      expect(JSON.stringify({ ...localStorage })).not.toContain('test-only-password');
      expect(JSON.stringify({ ...sessionStorage })).not.toContain('test-only-password');
    } finally { wrapper.unmount(); }
  });

  it('requires the current dynamic code with password when an authenticator is bound', async () => {
    const wrapper = mountSystemSettings(true);
    try {
      await flushPromises();
      expect(wrapper.find('[data-testid="begin-optional-totp"]').exists()).toBe(false);
      await wrapper.get('input[aria-label="当前管理员密码"]').setValue('test-only-password');
      await wrapper.get('input[aria-label="当前动态验证码"]').setValue('123456');
      await wrapper.get('[data-testid="identity-step-up"]').trigger('submit');
      await flushPromises();
      expect(requests).toEqual([{ path: '/api/v1/auth/step-up', body: { password: 'test-only-password', code: '123456' } }]);
      expect((wrapper.get('input[aria-label="当前动态验证码"]').element as HTMLInputElement).value).toBe('');
    } finally { wrapper.unmount(); }
  });

  it('starts enrollment only on explicit action and clears the setup key when cancelled or unmounted', async () => {
    const wrapper = mountSystemSettings(false, '2035-11-08T15:30:00Z');
    try {
      await flushPromises();
      await wrapper.get('[data-testid="begin-optional-totp"]').trigger('click');
      await flushPromises();
      expect(wrapper.text()).toContain('test-only-enrollment-key');
      expect(requests).toEqual([{ path: '/api/v1/auth/totp/setup', body: {} }]);
      expect(useSessionStore().sensitive.challengeId).toBe('11111111-1111-4111-8111-111111111111');
      await wrapper.get('[data-testid="cancel-optional-totp"]').trigger('click');
      expect(wrapper.text()).not.toContain('test-only-enrollment-key');
      expect(useSessionStore().sensitive.setupSecret).toBe('');
      expect(useSessionStore().session).toMatchObject({ authenticated: true, mfa_enabled: false });
      await wrapper.get('[data-testid="begin-optional-totp"]').trigger('click');
      await flushPromises();
      expect(useSessionStore().sensitive.setupSecret).toBe('test-only-enrollment-key');
    } finally { wrapper.unmount(); }
    expect(useSessionStore().sensitive.setupSecret).toBe('');
    expect(useSessionStore().sensitive.challengeId).toBe('');
  });

  it('confirms the explicit enrollment and removes one-time recovery codes after acknowledgement', async () => {
    const wrapper = mountSystemSettings(false, '2035-11-08T15:30:00Z');
    try {
      await flushPromises();
      await wrapper.get('[data-testid="begin-optional-totp"]').trigger('click');
      await flushPromises();
      await wrapper.get('input[aria-label="绑定验证码"]').setValue('654321');
      await wrapper.get('[data-testid="confirm-optional-totp"]').trigger('submit');
      await flushPromises();
      expect(requests[1]).toEqual({ path: '/api/v1/auth/totp/confirm', body: { challenge_id: '11111111-1111-4111-8111-111111111111', code: '654321' } });
      expect(useSessionStore().session).toMatchObject({ mfa_enabled: true });
      expect(wrapper.text()).toContain('test-only-recovery-code');
      expect(wrapper.text()).not.toContain('test-only-enrollment-key');
      expect(JSON.stringify({ ...localStorage })).not.toContain('test-only-recovery-code');
      await wrapper.get('[data-testid="acknowledge-optional-totp"]').trigger('click');
      expect(wrapper.text()).not.toContain('test-only-recovery-code');
      expect(useSessionStore().sensitive.recoveryCodes).toEqual([]);
    } finally { wrapper.unmount(); }
  });
});
