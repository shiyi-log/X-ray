import { createPinia, setActivePinia } from 'pinia';
import { createPersistedState } from 'pinia-plugin-persistedstate';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, nextTick } from 'vue';

import { useAccessStore } from './access';

describe('useAccessStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('updates accessMenus state', () => {
    const store = useAccessStore();
    expect(store.accessMenus).toEqual([]);
    store.setAccessMenus([{ name: 'Dashboard', path: '/dashboard' }]);
    expect(store.accessMenus).toEqual([
      { name: 'Dashboard', path: '/dashboard' },
    ]);
  });

  it('updates accessToken state correctly', () => {
    const store = useAccessStore();
    expect(store.accessToken).toBeNull(); // 初始状态
    store.setAccessToken('abc123');
    expect(store.accessToken).toBe('abc123');
  });

  it('returns the correct accessToken', () => {
    const store = useAccessStore();
    store.setAccessToken('xyz789');
    expect(store.accessToken).toBe('xyz789');
  });

  it('does not persist session or lock-screen credentials', async () => {
    const storage = {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
    };
    const pinia = createPinia();
    pinia.use(createPersistedState({ storage }));
    createApp({}).use(pinia);
    setActivePinia(pinia);
    const store = useAccessStore();
    store.setAccessToken('session-only');
    store.setRefreshToken('refresh-only');
    store.lockScreen('lock-only');
    await nextTick();

    expect(storage.getItem).not.toHaveBeenCalled();
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  // 测试设置空的访问菜单列表
  it('handles empty accessMenus correctly', () => {
    const store = useAccessStore();
    store.setAccessMenus([]);
    expect(store.accessMenus).toEqual([]);
  });

  // 测试设置空的访问路由列表
  it('handles empty accessRoutes correctly', () => {
    const store = useAccessStore();
    store.setAccessRoutes([]);
    expect(store.accessRoutes).toEqual([]);
  });
});
