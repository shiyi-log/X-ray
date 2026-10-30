import { createPinia } from 'pinia';
import { defineComponent, h, nextTick } from 'vue';
import {
  createMemoryHistory,
  createRouter,
  RouterView,
  type RouteRecordRaw,
} from 'vue-router';
import { flushPromises, mount } from '@vue/test-utils';

import { preferences, updatePreferences } from '@vben/preferences';

import LayoutContent from '../../../../packages/effects/layouts/src/basic/content/content.vue';

import { initComponentAdapter } from '@/adapter/components';
import { resourcesApi } from '@/api/resources';
import { useSessionStore } from '@/stores/session';

import { installSessionGuards } from './guards';
import { businessRoutes } from './index';

const pages = [
  ['/overview', '总览'],
  ['/cloud-accounts', '云账号'],
  ['/node-pools', '地区'],
  ['/nodes', '服务器管理'],
  ['/operations', '操作中心'],
  ['/access-profiles', '访问配置'],
  ['/subscriptions', '订阅'],
  ['/audit', '审计日志'],
  ['/system', '系统设置'],
  ['/operations/local-operation', '操作详情'],
] as const;

const dialogs: Record<string, [string, string]> = {
  '/cloud-accounts': ['添加账号', '添加云账号'],
  '/node-pools': ['地区分配', '地区分配'],
  '/nodes': ['创建服务器', '创建服务器'],
  '/access-profiles': ['新建访问配置', '新建访问配置'],
};

async function finishTransition() {
  await flushPromises();
  // Vue's real CSS transition completes after two animation frames.
  await new Promise((resolve) => setTimeout(resolve, 80));
  await flushPromises();
  await nextTick();
}

describe('business page navigation inside the Vben content layout', () => {
  it('opens every real page and can revisit pages with transitions enabled', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const fetch = vi.fn(async (input: string) => {
      if (input !== '/api/v1/operations/local-operation/') {
        throw new Error('Unexpected network request');
      }
      return new Response(JSON.stringify({
        id: 'local-operation', kind: '', status: 'SUCCEEDED',
        steps: [], revocation_nodes: [], can_cancel: false,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    vi.stubGlobal('fetch', fetch);
    const page = { items: [], total: 0, page: 1, page_size: 20 };
    vi.spyOn(resourcesApi, 'overview').mockResolvedValue({
      security_mode: 'NORMAL', counts: {}, recent_operations: [], recent_audit: [],
    } as never);
    vi.spyOn(resourcesApi, 'system').mockResolvedValue({
      version: 'local-test', environment: 'test', debug: false,
      allowed_hosts: [], csrf_trusted_origins: [],
    } as never);
    for (const name of [
      'cloudAccounts', 'nodePools', 'nodes', 'operations',
      'accessProfiles', 'subscriptions', 'auditEvents',
    ] as const) {
      vi.spyOn(resourcesApi, name).mockResolvedValue(page);
    }
    const pinia = createPinia();
    useSessionStore(pinia).applySession({
      authenticated: true, mfa_required: false,
      admin: { username: 'local-test' }, expires_at: null, recent_auth_until: null,
    });
    const root = businessRoutes.find((route) => route.name === 'Root')!;
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ ...root, component: LayoutContent } as RouteRecordRaw],
    });
    installSessionGuards(router);
    const savedTransition = { ...preferences.transition };
    const savedKeepAlive = preferences.tabbar.keepAlive;
    updatePreferences({
      transition: { enable: true, name: 'fade-slide' },
      tabbar: { keepAlive: true },
    });

    await router.push('/overview');
    const wrapper = mount(defineComponent({ render: () => h(RouterView) }), {
      attachTo: document.body,
      global: {
        plugins: [pinia, router, { install: initComponentAdapter }],
        stubs: { transition: false, 'transition-group': false },
      },
    });
    try {
      for (const [path, title] of [...pages, pages[1], pages[0]]) {
        await router.push(path);
        await finishTransition();
        expect(wrapper.find('h1').exists(), `missing page heading for ${path}`).toBe(true);
        expect(wrapper.get('h1').text()).toBe(title);
        expect(wrapper.find('[role="alert"]').exists(), `${path}: ${wrapper.text()}`).toBe(false);
        expect(wrapper.find('[role="status"]').exists(), `still loading ${path}`).toBe(false);

        if (path === '/nodes') {
          const regionsButton = wrapper.findAll('button').find((item) => item.text().trim() === '地区');
          expect(regionsButton, 'missing region quota entry on server management').toBeDefined();
          await regionsButton!.trigger('click');
          await finishTransition();
          expect(router.currentRoute.value.path).toBe('/node-pools');
          expect(wrapper.get('h1').text()).toBe('地区');
          await router.push('/nodes');
          await finishTransition();
        }

        const dialogAction = dialogs[path];
        if (dialogAction) {
          const [buttonText, dialogTitle] = dialogAction;
          const button = wrapper.findAll('button').find((item) => item.text() === buttonText)!;
          await button.trigger('click');
          await finishTransition();
          const dialog = [...document.querySelectorAll<HTMLElement>('[role="dialog"]')]
            .find((item) => item.style.display !== 'none');
          expect(dialog, `missing dialog on ${path}`).toBeDefined();
          expect(dialog!.textContent).toContain(dialogTitle);
          (dialog!.querySelector('.ant-modal-close') as HTMLButtonElement).click();
          await vi.waitFor(() => {
            expect(dialog!.style.display === 'none').toBe(true);
          });
        }
      }

      vi.mocked(resourcesApi.nodes).mockRejectedValueOnce(new Error('本地模拟网络错误'));
      await router.push('/nodes');
      await finishTransition();
      expect(wrapper.get('h1').text()).toBe('服务器管理');
      expect(wrapper.get('[role="alert"]').text()).toContain('本地模拟网络错误');
      await wrapper.get('[aria-label="重试"]').trigger('click');
      await flushPromises();
      expect(wrapper.find('[role="alert"]').exists()).toBe(false);
      expect(wrapper.text()).toContain('暂无服务器');
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(warn.mock.calls.map((args) => String(args[0]))).toEqual([]);
      expect(error).not.toHaveBeenCalled();
    } finally {
      wrapper.unmount();
      updatePreferences({
        transition: savedTransition,
        tabbar: { keepAlive: savedKeepAlive },
      });
      vi.unstubAllGlobals();
    }
  }, 15_000);
});
