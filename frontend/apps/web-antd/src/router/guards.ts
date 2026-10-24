import type { Router } from 'vue-router';

import { useSessionStore } from '@/stores/session';

export function installSessionGuards(router: Router) {
  router.beforeEach(async (to) => {
    const session = useSessionStore();
    if (!session.loaded) {
      try {
        await session.loadSession();
      } catch {
        session.applySession(null);
      }
    }
    if (to.meta.public && session.authenticated && to.path === '/login') {
      return { name: 'overview' };
    }
    if (!to.meta.public && !session.authenticated) {
      return { name: 'login', query: { redirect: to.fullPath } };
    }
    return true;
  });
}
