import { DOMWrapper, flushPromises, mount } from '@vue/test-utils';

import { resetCsrfToken } from '@/api/request';
import { resourcesApi, type SystemInfo } from '@/api/resources';

import SystemSettings from './index.vue';

const runningJob = {
  id: '11111111-1111-4111-8111-111111111111',
  version: '0.15.0', status: 'RUNNING', phase: 'BACKUP', error_code: '',
  created_at: '2026-11-14T00:00:00Z', updated_at: '2026-11-14T00:00:01Z',
};
const catalog = {
  current_version: '0.14.9', available: true, reason: '',
  candidates: [{ version: '0.15.0', published_at: '2026-11-14T00:00:00Z', notes: '改进分配保存与在线升级' }],
  jobs: [] as (typeof runningJob)[],
};
const systemInfo = {
  version: '0.14.9', environment: 'test', debug: false, allowed_hosts: [], csrf_trusted_origins: [],
  provider_identity_network: { enabled: true, source: 'DATABASE' },
  node_status_sync: { enabled: false, interval_minutes: 60, last_scheduled_at: null, source: 'DEFAULT' },
  node_pool_sync: { enabled: false, interval_minutes: 15, creation_templates: [], last_scheduled_at: null, source: 'DEFAULT' },
  node_daily_restart: { enabled: false, time: '04:00', timezone: 'Asia/Shanghai', last_scheduled_at: null, source: 'DEFAULT' },
  usage_sync: { enabled: false, interval_minutes: 1, last_scheduled_at: null, source: 'DEFAULT' },
} satisfies SystemInfo;

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function mountSettings() {
  vi.spyOn(resourcesApi, 'system').mockResolvedValue(systemInfo);
  return mount(SystemSettings, { attachTo: document.body, global: { stubs: { SecuritySettings: true, transition: false, 'transition-group': false } } });
}

function button(root: DOMWrapper<Element> | ReturnType<typeof mountSettings>, label: string) {
  return root.findAll('button').find((item) => item.text().replace(/\s/g, '').includes(label))!;
}

async function openDialog(wrapper: ReturnType<typeof mountSettings>) {
  await flushPromises();
  const entry = button(wrapper, '在线升级');
  expect(entry, '系统设置应提供在线升级入口').toBeDefined();
  await entry.trigger('click');
  await flushPromises();
  return new DOMWrapper(document.querySelector('[role="dialog"]')!);
}

describe('online system upgrade', () => {
  beforeEach(() => resetCsrfToken());
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('checks available releases and submits the selected version only after confirmation', async () => {
    const writes: { path: string; payload: unknown; key: string | null }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith('/csrf')) return response({ csrf_token: 'fixture-csrf' });
      if (init?.method === 'POST') {
        writes.push({ path, payload: JSON.parse(String(init.body)), key: new Headers(init.headers).get('Idempotency-Key') });
        return response({ ...runningJob, status: 'QUEUED', phase: 'QUEUED' }, 202);
      }
      return response(catalog);
    }));
    const wrapper = mountSettings();
    try {
      const dialog = await openDialog(wrapper);
      expect(dialog.text()).toContain('0.14.9');
      expect(dialog.text()).toContain('0.15.0');
      expect(dialog.text()).toContain('改进分配保存');
      expect(dialog.text()).toContain('备份');
      expect(writes).toEqual([]);
      await button(dialog, '确认升级').trigger('click');
      await flushPromises();
      expect(writes).toEqual([{ path: '/api/v1/system/upgrade/', payload: { version: '0.15.0', confirmation: '确认在线升级' }, key: expect.stringMatching(/^[0-9a-f-]{36}$/) }]);
      expect(dialog.text()).toContain('等待执行');
      expect(button(dialog, '确认升级').attributes('disabled')).toBeDefined();
    } finally { wrapper.unmount(); }
  });

  it('disables upgrade when the deployment agent is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ ...catalog, available: false, reason: 'NOT_CONFIGURED' })));
    const wrapper = mountSettings();
    try {
      const dialog = await openDialog(wrapper);
      expect(dialog.text()).toContain('尚未启用在线升级');
      expect(button(dialog, '确认升级').attributes('disabled')).toBeDefined();
    } finally { wrapper.unmount(); }
  });

  it('shows no available release and disables the confirmation when the catalog is empty', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ ...catalog, candidates: [] })));
    const wrapper = mountSettings();
    try {
      const dialog = await openDialog(wrapper);
      expect(dialog.text()).toContain('暂无可用更新');
      expect(button(dialog, '确认升级').attributes('disabled')).toBeDefined();
    } finally { wrapper.unmount(); }
  });

  it('shows a failed result without rendering raw agent diagnostics', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ ...catalog, jobs: [{ ...runningJob, status: 'FAILED', phase: 'FAILED', error_code: 'fixture-secret-diagnostic' }] })));
    const wrapper = mountSettings();
    try {
      const dialog = await openDialog(wrapper);
      expect(dialog.text()).toContain('升级失败');
      expect(dialog.text()).toContain('核对服务和备份');
      expect(dialog.text()).not.toContain('fixture-secret-diagnostic');
    } finally { wrapper.unmount(); }
  });

  it('keeps a running upgrade pending during a disconnect, resumes polling and stops after success', async () => {
    let reads = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      reads += 1;
      if (reads === 2) throw new TypeError('fixture connection lost');
      return response({ ...catalog, current_version: reads > 2 ? '0.15.0' : '0.14.9', jobs: [{ ...runningJob, status: reads > 2 ? 'SUCCEEDED' : 'RUNNING', phase: reads > 2 ? 'COMPLETE' : 'BACKUP' }] });
    }));
    const wrapper = mountSettings();
    try {
      vi.useFakeTimers();
      const dialog = await openDialog(wrapper);
      expect(dialog.text()).toContain('正在备份');
      await vi.advanceTimersByTimeAsync(3000);
      await flushPromises();
      expect(dialog.text()).toContain('正在重新连接');
      expect(dialog.text()).not.toContain('升级失败');
      await vi.advanceTimersByTimeAsync(3000);
      await flushPromises();
      expect(dialog.text()).toContain('升级成功');
      expect(dialog.text()).toContain('0.15.0');
      const finishedReads = reads;
      await vi.advanceTimersByTimeAsync(9000);
      expect(reads).toBe(finishedReads);
    } finally { wrapper.unmount(); }
  });

  it('requires the normal identity verification after a step-up rejection', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/csrf')) return response({ csrf_token: 'fixture-csrf' });
      return init?.method === 'POST' ? response({ code: 'STEP_UP_REQUIRED', message: 'fixture raw error text' }, 403) : response(catalog);
    }));
    const wrapper = mountSettings();
    try {
      const dialog = await openDialog(wrapper);
      await button(dialog, '确认升级').trigger('click');
      await flushPromises();
      expect(dialog.text()).toContain('账号安全');
      expect(dialog.text()).toContain('重新验证身份');
      expect(dialog.text()).not.toContain('fixture raw error text');
      expect(dialog.text()).not.toContain('升级成功');
    } finally { wrapper.unmount(); }
  });

  it('does not replace a new running job with an older successful job from a stale poll', async () => {
    let reads = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/csrf')) return response({ csrf_token: 'fixture-csrf' });
      if (init?.method === 'POST') return response(runningJob, 202);
      reads += 1;
      return response({ ...catalog, jobs: reads > 1 ? [{ ...runningJob, id: '22222222-2222-4222-8222-222222222222', status: 'SUCCEEDED', phase: 'COMPLETE' }] : [] });
    }));
    const wrapper = mountSettings();
    try {
      vi.useFakeTimers();
      const dialog = await openDialog(wrapper);
      await button(dialog, '确认升级').trigger('click');
      await flushPromises();
      await vi.advanceTimersByTimeAsync(3000);
      await flushPromises();
      expect(dialog.text()).toContain('正在备份');
      expect(dialog.text()).not.toContain('升级成功');
    } finally { wrapper.unmount(); }
  });

  it('reuses the request key after an uncertain submission and clears polling on unmount', async () => {
    const keys: (string | null)[] = [];
    let reads = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/csrf')) return response({ csrf_token: 'fixture-csrf' });
      if (init?.method === 'POST') {
        keys.push(new Headers(init.headers).get('Idempotency-Key'));
        if (keys.length === 1) throw new TypeError('fixture uncertain submission');
        return response({ ...runningJob, status: 'QUEUED', phase: 'QUEUED' }, 202);
      }
      reads += 1;
      return response(catalog);
    }));
    const wrapper = mountSettings();
    vi.useFakeTimers();
    const dialog = await openDialog(wrapper);
    await button(dialog, '确认升级').trigger('click');
    await flushPromises();
    expect(dialog.text()).toContain('尚未确认');
    await button(dialog, '确认升级').trigger('click');
    await flushPromises();
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
    wrapper.unmount();
    const stoppedReads = reads;
    await vi.advanceTimersByTimeAsync(6000);
    expect(reads).toBe(stoppedReads);
  });
});
