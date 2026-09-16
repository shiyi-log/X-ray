import { createRouter, createWebHistory } from 'vue-router';

import { installSessionGuards } from './guards';

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/auth/login.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      redirect: '/overview',
    },
    {
      path: '/overview',
      name: 'overview',
      component: () => import('@/views/overview/index.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/overview',
    },
  ],
});

installSessionGuards(router);
