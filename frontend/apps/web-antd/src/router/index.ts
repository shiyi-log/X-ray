import type { RouteRecordRaw } from 'vue-router';

import { createRouter, createWebHistory } from 'vue-router';
import {
  Activity,
  Cloud,
  Layers3,
  LayoutDashboard,
  Network,
  Rss,
  ScrollText,
  Server,
  Settings2,
} from 'lucide-vue-next';

import { useAccessStore } from '@vben/stores';
import { generateMenus } from '@vben/utils';

import { installSessionGuards } from './guards';

export const businessRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Authentication',
    component: () => import('@/layouts/auth.vue'),
    meta: { public: true, hideInMenu: true, title: '登录' },
    children: [
      {
        path: '',
        name: 'login',
        component: () => import('@/views/auth/login.vue'),
        meta: { public: true, hideInMenu: true, title: '登录' },
      },
    ],
  },
  {
    path: '/',
    name: 'Root',
    component: () => import('@/layouts/basic.vue'),
    redirect: '/overview',
    meta: { hideInBreadcrumb: true, title: 'X-ray Manager' },
    children: [
      {
        path: 'overview',
        name: 'overview',
        component: () => import('@/views/overview/index.vue'),
        meta: { title: '总览', icon: LayoutDashboard, order: 10 },
      },
      {
        path: 'cloud-accounts',
        name: 'cloud-accounts',
        component: () => import('@/views/cloud-accounts/index.vue'),
        meta: { title: '云账号', icon: Cloud, order: 20 },
      },
      {
        path: 'node-pools',
        name: 'node-pools',
        component: () => import('@/views/node-pools/index.vue'),
        meta: { title: '节点池', icon: Layers3, order: 30 },
      },
      {
        path: 'nodes',
        name: 'nodes',
        component: () => import('@/views/nodes/index.vue'),
        meta: { title: '节点', icon: Server, order: 40 },
      },
      {
        path: 'operations',
        name: 'operations',
        component: () => import('@/views/operations/index.vue'),
        meta: { title: '操作中心', icon: Activity, order: 50 },
      },
      {
        path: 'operations/:id',
        name: 'operation-detail',
        component: () => import('@/views/operations/detail.vue'),
        meta: { title: '操作详情', hideInMenu: true, hideInTab: true },
      },
      {
        path: 'access-profiles',
        name: 'access-profiles',
        component: () => import('@/views/access-profiles/index.vue'),
        meta: { title: '访问配置', icon: Network, order: 60 },
      },
      {
        path: 'subscriptions',
        name: 'subscriptions',
        component: () => import('@/views/subscriptions/index.vue'),
        meta: { title: '订阅管理', icon: Rss, order: 70 },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/audit/index.vue'),
        meta: { title: '审计日志', icon: ScrollText, order: 80 },
      },
      {
        path: 'system',
        name: 'system',
        component: () => import('@/views/system/index.vue'),
        meta: { title: '系统设置', icon: Settings2, order: 90 },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    redirect: '/overview',
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes: businessRoutes,
  scrollBehavior: (_to, _from, savedPosition) =>
    savedPosition ?? { left: 0, top: 0 },
});

export function initializeStaticAccess() {
  const access = useAccessStore();
  const root = businessRoutes.find((route) => route.name === 'Root');
  access.setAccessMenus(
    generateMenus((root?.children ?? []) as RouteRecordRaw[], router),
  );
  access.setAccessRoutes(
    businessRoutes.filter((route) => route.name === 'Root'),
  );
  access.setIsAccessChecked(true);
  // X-ray authorizes with a server session; bearer tokens stay unused.
  access.setAccessToken(null);
  access.setRefreshToken(null);
}

installSessionGuards(router);
