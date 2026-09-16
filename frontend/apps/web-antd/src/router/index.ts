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
      component: () => import('@/layouts/AdminShell.vue'),
      children: [
        { path: '', redirect: '/overview' },
        {
          path: 'overview',
          name: 'overview',
          component: () => import('@/views/overview/index.vue'),
        },
        {
          path: 'cloud-accounts',
          name: 'cloud-accounts',
          component: () => import('@/views/cloud-accounts/index.vue'),
        },
        {
          path: 'node-pools',
          name: 'node-pools',
          component: () => import('@/views/node-pools/index.vue'),
        },
        { path: 'nodes', name: 'nodes', component: () => import('@/views/nodes/index.vue') },
        {
          path: 'operations',
          name: 'operations',
          component: () => import('@/views/operations/index.vue'),
        },
        {
          path: 'operations/:id',
          name: 'operation-detail',
          component: () => import('@/views/operations/detail.vue'),
        },
        {
          path: 'access-profiles',
          name: 'access-profiles',
          component: () => import('@/views/access-profiles/index.vue'),
        },
        {
          path: 'subscriptions',
          name: 'subscriptions',
          component: () => import('@/views/subscriptions/index.vue'),
        },
        { path: 'audit', name: 'audit', component: () => import('@/views/audit/index.vue') },
        { path: 'system', name: 'system', component: () => import('@/views/system/index.vue') },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/overview',
    },
  ],
});

installSessionGuards(router);
