import { createMemoryHistory, createRouter } from 'vue-router';
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils';

import {
  resourcesApi,
  type ActionPreview,
  type CloudAccount,
  type ManagedNode,
} from '@/api/resources';
import { ApiError } from '@/api/request';

import Nodes from './index.vue';

const node = {
  id: 'node-1',
  name: '新加坡服务器',
  external_id: 'instance-1',
  provider: 'aws_lightsail',
  region: 'ap-southeast-1',
  addresses: [
    { value: '203.0.113.10', family: 4, kind: 'dynamic', resource_id: 'instance-1' },
    { value: '2001:db8::10', family: 6, kind: 'dynamic', resource_id: 'instance-1' },
  ],
  raw_cloud_state: 'RUNNING',
  desired_state: 'PRESENT',
  provisioning_state: 'READY',
  health_state: 'READY',
  security_state: 'OPEN',
  metering_coverage: 'SUPPORTED',
  traffic_state: 'COLLECTED',
  traffic_upload_bytes: 1024 ** 3,
  traffic_download_bytes: 2 * 1024 ** 3,
  traffic_total_bytes: 3 * 1024 ** 3,
  traffic_sampled_at: '2026-10-30T10:00:00Z',
} as ManagedNode;

const account = {
  id: 'account-1',
  name: '测试账号',
  enabled: true,
  provider: 'aws_lightsail',
} as CloudAccount;

function mockNodes(items: ManagedNode[] = [node]) {
  vi.spyOn(resourcesApi, 'nodes').mockResolvedValue({
    items,
    total: items.length,
    page: 1,
    page_size: 20,
  });
}

function mountNodes() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/operations/:id', component: { template: '<div />' } },
    ],
  });
  const wrapper = mount(Nodes, {
    attachTo: document.body,
    global: { plugins: [router], stubs: { transition: false, 'transition-group': false } },
  });
  return { wrapper, router };
}

describe('server management', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows IP, running status, traffic totals and detail/action controls', async () => {
    mockNodes();
    vi.spyOn(resourcesApi, 'nodeDetail').mockResolvedValue(node);
    const { wrapper } = mountNodes();

    try {
      await flushPromises();
      const text = wrapper.text();
      expect(text).toContain('服务器管理');
      expect(text).toContain('203.0.113.10');
      expect(text).not.toContain('2001:db8::10');
      expect(text).toContain('运行中');
      expect(text).toContain('3.00 GiB');
      expect(text).toContain('上行 1.00 GiB · 下行 2.00 GiB');
      for (const action of ['启动', '重启', '详情', '删除']) {
        expect(wrapper.findAll('button').some((button) => button.text().includes(action))).toBe(true);
      }
      expect(text).not.toContain('暂停创建');
      expect(text).not.toContain('恢复创建');
      expect(text).not.toContain('节点池');

      await wrapper.findAll('button').find((button) => button.text().includes('详情'))!.trigger('click');
      await flushPromises();
      expect(resourcesApi.nodeDetail).toHaveBeenCalledWith('node-1');
      expect(document.body.textContent).toContain('服务器详情');
      expect(document.body.textContent).toContain('203.0.113.10');
      expect(document.body.textContent).not.toContain('2001:db8::10');
    } finally {
      wrapper.unmount();
    }
  });

  it('accepts legacy IPv4 strings and hides IPv6 or invalid address values', async () => {
    mockNodes([{
      ...node,
      addresses: [
        '198.51.100.4',
        '2001:db8::20',
        '999.0.0.1',
        { value: '192.0.2.5', family: 6 },
        { value: '192.0.2.6', family: 4 },
      ],
    } as ManagedNode]);
    const { wrapper } = mountNodes();

    try {
      await flushPromises();
      const text = wrapper.text();
      expect(text).toContain('198.51.100.4');
      expect(text).toContain('192.0.2.6');
      expect(text).not.toContain('2001:db8::20');
      expect(text).not.toContain('999.0.0.1');
      expect(text).not.toContain('192.0.2.5');
    } finally {
      wrapper.unmount();
    }
  });

  it.each([
    ['starting', '启动中'],
    ['stopping', '停止中'],
    ['rebooting', '重启中'],
    ['shutting-down', '关机中'],
    ['terminated', '已终止'],
    ['provider-specific-state', '未知'],
  ])('shows %s as a Chinese runtime status', async (rawState, expected) => {
    mockNodes([{ ...node, raw_cloud_state: rawState } as ManagedNode]);
    const { wrapper } = mountNodes();

    try {
      await flushPromises();
      expect(wrapper.text()).toContain(expected);
      if (expected === '未知') expect(wrapper.text()).not.toContain('PROVIDER-SPECIFIC-STATE');
    } finally {
      wrapper.unmount();
    }
  });

  it('disables cloud actions until an instance exists while keeping details available', async () => {
    mockNodes([{ ...node, id: 'reserved-node', external_id: '' } as ManagedNode]);
    const { wrapper } = mountNodes();

    try {
      await flushPromises();
      const button = (label: string) => wrapper.findAll('button').find((item) => item.text().includes(label))!;
      expect(button('启动').element.hasAttribute('disabled')).toBe(true);
      expect(button('重启').element.hasAttribute('disabled')).toBe(true);
      expect(button('删除').element.hasAttribute('disabled')).toBe(true);
      expect(button('详情').element.hasAttribute('disabled')).toBe(false);
    } finally {
      wrapper.unmount();
    }
  });

  it('disables cloud actions for deleted instances while keeping details available', async () => {
    mockNodes([{ ...node, id: 'deleted-node', desired_state: 'DELETED' } as ManagedNode]);
    const { wrapper } = mountNodes();

    try {
      await flushPromises();
      const button = (label: string) => wrapper.findAll('button').find((item) => item.text().includes(label))!;
      expect(button('启动').element.hasAttribute('disabled')).toBe(true);
      expect(button('重启').element.hasAttribute('disabled')).toBe(true);
      expect(button('删除').element.hasAttribute('disabled')).toBe(true);
      expect(button('详情').element.hasAttribute('disabled')).toBe(false);
    } finally {
      wrapper.unmount();
    }
  });

  it('creates a server from account and region without a pool field', async () => {
    mockNodes([]);
    vi.spyOn(resourcesApi, 'cloudAccounts').mockResolvedValue({
      items: [account], total: 1, page: 1, page_size: 20,
    });
    vi.spyOn(resourcesApi, 'capabilities').mockResolvedValue({
      items: [
        {
          name: 'instance', status: 'SUPPORTED',
          regions: ['ap-southeast-1', 'ap-northeast-1'], plans: [],
          reason: 'local fixture', checked_at: '2026-10-30T10:00:00Z', live_verified: false,
        },
        {
          name: 'catalog', status: 'UNVERIFIED', regions: ['us-east-1'], plans: [],
          reason: 'local fixture', checked_at: '2026-10-30T10:00:00Z', live_verified: false,
        },
      ],
    });
    vi.spyOn(resourcesApi, 'nodePools').mockResolvedValue({
      items: [{
        id: 'pool-1', name: 'IP', region: 'ap-southeast-1', quota: 5,
        used: 2, available: 3,
        regions: ['ap-southeast-1', 'ap-northeast-1', 'us-east-1'],
        allocations: [
          { region: 'ap-southeast-1', quota: 2, used: 2, available: 0 },
          { region: 'ap-northeast-1', quota: 1, used: 0, available: 1 },
          { region: 'us-east-1', quota: 2, used: 0, available: 2 },
        ],
      }],
      total: 1, page: 1, page_size: 20,
    });
    const createNode = vi.spyOn(resourcesApi, 'createNode').mockResolvedValue({
      operation_id: 'create-operation', status: 'PENDING', target_type: 'node', target_id: 'node-1',
    });
    vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000001' });
    const { wrapper, router } = mountNodes();

    try {
      await flushPromises();
      await wrapper.findAll('button').find((button) => button.text().includes('创建服务器'))!.trigger('click');
      await flushPromises();
      const dialogElement = [...document.body.querySelectorAll<HTMLElement>('[role="dialog"]')]
        .find((item) => item.style.display !== 'none')!;
      const dialog = new DOMWrapper(dialogElement);
      expect(dialog.text()).not.toContain('节点池');
      const state = (wrapper.vm.$ as unknown as { setupState: {
        accountChanged: (id: string) => Promise<void>;
        form: { account_id: string; image_id: string; plan_id: string; region: string };
        regionOptions: { label: string; value: string; disabled: boolean }[];
      } }).setupState;
      state.form.account_id = 'account-1';
      await state.accountChanged('account-1');
      expect(state.regionOptions).toEqual([
        { label: 'ap-southeast-1（可用 0）', value: 'ap-southeast-1', disabled: true },
        { label: 'ap-northeast-1（可用 1）', value: 'ap-northeast-1', disabled: false },
      ]);
      await dialog.get('[aria-label="套餐 ID"]').setValue('nano_3_0');
      await dialog.get('[aria-label="镜像 ID"]').setValue('ubuntu_24_04');

      state.form.region = 'ap-southeast-1';
      await dialog.findAll('button').find((button) => button.text().includes('提交创建操作'))!.trigger('click');
      await flushPromises();
      expect(createNode).not.toHaveBeenCalled();
      expect(dialog.text()).toContain('所选地区未分配或已无可用额度');

      state.form.region = 'us-east-1';
      await dialog.findAll('button').find((button) => button.text().includes('提交创建操作'))!.trigger('click');
      await flushPromises();
      expect(createNode).not.toHaveBeenCalled();

      state.form.region = 'ap-northeast-1';
      await dialog.findAll('button').find((button) => button.text().includes('提交创建操作'))!.trigger('click');
      await flushPromises();

      expect(createNode).toHaveBeenCalledWith({
        account_id: 'account-1',
        region: 'ap-northeast-1',
        plan_id: 'nano_3_0',
        image_id: 'ubuntu_24_04',
      }, '00000000-0000-4000-8000-000000000001');
      expect(router.currentRoute.value.fullPath).toBe('/operations/create-operation');
    } finally {
      wrapper.unmount();
    }
  });

  it('submits start and restart through the existing node-action route', async () => {
    mockNodes();
    const nodeAction = vi.spyOn(resourcesApi, 'nodeAction').mockResolvedValue({
      operation_id: 'node-operation', status: 'PENDING', target_type: 'node', target_id: 'node-1',
    });
    const { wrapper } = mountNodes();

    try {
      await flushPromises();
      await wrapper.findAll('button').find((button) => button.text().includes('启动'))!.trigger('click');
      await flushPromises();
      expect(nodeAction).toHaveBeenNthCalledWith(1, 'node-1', 'start');
      await wrapper.findAll('button').find((button) => button.text().includes('重启'))!.trigger('click');
      await flushPromises();
      expect(nodeAction).toHaveBeenNthCalledWith(2, 'node-1', 'reboot');
    } finally {
      wrapper.unmount();
    }
  });

  it('explains that start and restart require fresh authentication', async () => {
    mockNodes();
    vi.spyOn(resourcesApi, 'nodeAction').mockRejectedValue(new ApiError(403, {
      code: 'STEP_UP_REQUIRED',
      message: '近期身份验证已过期',
    }));
    const { wrapper } = mountNodes();

    try {
      await flushPromises();
      await wrapper.findAll('button').find((button) => button.text().includes('启动'))!.trigger('click');
      await flushPromises();
      expect(wrapper.text()).toContain('请退出并重新完成密码与 MFA 验证后再次操作');
    } finally {
      wrapper.unmount();
    }
  });

  it('requires a fresh preview, exact confirmation, and a new idempotency key for deletion', async () => {
    mockNodes();
    const preview: ActionPreview = {
      id: 'preview-1',
      kind: 'node.delete',
      target_id: 'node-1',
      required_phrase: '确认删除服务器',
      expires_at: new Date(Date.now() + 300_000).toISOString(),
      snapshot: {},
    };
    const createPreview = vi.spyOn(resourcesApi, 'createPreview').mockResolvedValue(preview);
    const nodeAction = vi.spyOn(resourcesApi, 'nodeAction').mockResolvedValue({
      operation_id: 'delete-operation', status: 'PENDING', target_type: 'node', target_id: 'node-1',
    });
    vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000002' });
    const { wrapper, router } = mountNodes();

    try {
      await flushPromises();
      await wrapper.findAll('button').find((button) => button.text().includes('删除'))!.trigger('click');
      await flushPromises();
      expect(createPreview).toHaveBeenCalledWith({ kind: 'node.delete', target_id: 'node-1', params: {} });
      expect(document.body.textContent).toContain('确认删除服务器');

      const input = document.body.querySelector<HTMLInputElement>('[aria-label="确认文本"]')!;
      await new DOMWrapper(input).setValue('确认删除服务器');
      await new DOMWrapper(document.body.querySelector('[data-testid="danger-submit"]')!).trigger('click');
      await flushPromises();

      expect(nodeAction).toHaveBeenCalledWith(
        'node-1',
        'delete',
        { preview_id: 'preview-1', confirmation: '确认删除服务器' },
        '00000000-0000-4000-8000-000000000002',
      );
      expect(router.currentRoute.value.fullPath).toBe('/operations/delete-operation');
    } finally {
      wrapper.unmount();
    }
  });
});
