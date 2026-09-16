import type { Router } from 'vue-router';

import { useSessionStore } from '@/stores/session';

export function installSessionGuards(router: Router) {
  router.beforeEach(async (to) => {
    const session = useSessionStore();
    if (!session.loaded) {
      try {
        await session.loadSession();
      } catch {
        session.session = null;
        session.loaded = true;
      }
    }
    if (to.meta.public && session.authenticated && to.name === 'login') {
      return { name: 'overview' };
    }
    if (!to.meta.public && !session.authenticated) {
      return { name: 'login', query: { redirect: to.fullPath } };
    }
    return true;
  });
}
