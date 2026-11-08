import { createPinia, setActivePinia } from 'pinia';
import {
  createMemoryHistory,
  createRouter,
  type RouteRecordRaw,
} from 'vue-router';

import { useAccessStore } from '@vben/stores';

import { useSessionStore } from '@/stores/session';

import { installSessionGuards } from './guards';
import { businessRoutes, initializeStaticAccess } from './index';

describe('X-ray Vben route shell', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('builds absolute menus from the business routes only', () => {
    initializeStaticAccess();

    const access = useAccessStore();
    const menuPaths = access.accessMenus.map((menu) => menu.path);

    expect(menuPaths).toEqual([
      '/overview',
      '/cloud-accounts',
      '/subscriptions',
      '/nodes',
      '/operations',
      '/audit',
      '/system',
    ]);
    expect(menuPaths).not.toContain('/node-pools');
    expect(menuPaths).not.toContain('/access-profiles');
    const root = businessRoutes.find((route) => route.name === 'Root');
    const subscriptionRoute = root?.children?.find((route) => route.name === 'subscriptions');
    expect(subscriptionRoute?.meta?.order).toBe(30);
    expect(menuPaths).not.toContain('/operations/:id');
    expect(access.accessToken).toBeNull();
    expect(access.refreshToken).toBeNull();
  });

  it('keeps the legacy access profile URL as a single subscription-pool entry', () => {
    const root = businessRoutes.find((route) => route.name === 'Root');
    const legacyRoute = root?.children?.find((route) => route.name === 'access-profiles');

    expect(legacyRoute?.redirect).toBe('/subscriptions');
    expect(legacyRoute?.meta?.hideInMenu).toBe(true);
  });

  it('keeps the Vben authentication parent separate from the login form route', () => {
    const authentication = businessRoutes.find(
      (route) => route.name === 'Authentication',
    );
    expect(authentication?.path).toBe('/login');
    expect(authentication?.children?.[0]?.name).toBe('login');
    expect(authentication?.children?.[0]?.path).toBe('');
  });

  it('redirects anonymous users to login and authenticated users away from login', async () => {
    // Exercise the real route metadata and guard without mounting business views.
    const component = { template: '<div />' };
    const testRoutes: RouteRecordRaw[] = businessRoutes.map((route) => {
      const testRoute = { ...route, component } as RouteRecordRaw;
      if (route.children) {
        testRoute.children = route.children.map(
          (child) => ({ ...child, component }) as RouteRecordRaw,
        );
      }
      return testRoute;
    });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: testRoutes,
    });
    installSessionGuards(router);
    const fetchSession = vi.fn(async () => new Response(
      JSON.stringify({
        authenticated: false,
        mfa_required: false,
        mfa_enabled: false,
        expires_at: null,
        recent_auth_until: null,
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchSession);

    await router.push('/overview');
    expect(router.currentRoute.value.path).toBe('/login');
    expect(router.currentRoute.value.query.redirect).toBe('/overview');

    useSessionStore().applySession({
      authenticated: true,
      mfa_required: false,
      mfa_enabled: false,
      admin: { username: 'admin' },
      expires_at: null,
      recent_auth_until: null,
    });
    await router.push('/login');
    expect(router.currentRoute.value.path).toBe('/overview');
    expect(fetchSession).toHaveBeenCalledTimes(1);
    expect(fetchSession).toHaveBeenCalledWith(
      '/api/v1/auth/session',
      expect.objectContaining({ method: 'GET', credentials: 'same-origin' }),
    );
  });
});
