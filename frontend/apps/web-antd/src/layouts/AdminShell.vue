<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  Activity,
  Boxes,
  Cloud,
  FileClock,
  Gauge,
  KeyRound,
  ListChecks,
  LogOut,
  Menu,
  Server,
  Settings,
  ShieldCheck,
  X,
} from 'lucide-vue-next';

import { useSessionStore } from '@/stores/session';

const router = useRouter();
const session = useSessionStore();
const mobileOpen = ref(false);
const navigation = [
  { to: '/overview', label: '总览', icon: Gauge },
  { to: '/cloud-accounts', label: '云账号', icon: Cloud },
  { to: '/node-pools', label: '节点池', icon: Boxes },
  { to: '/nodes', label: '节点', icon: Server },
  { to: '/operations', label: '操作中心', icon: Activity },
  { to: '/access-profiles', label: '访问配置', icon: KeyRound },
  { to: '/subscriptions', label: '订阅', icon: ListChecks },
  { to: '/audit', label: '审计', icon: FileClock },
  { to: '/system', label: '系统', icon: Settings },
];

async function logout() {
  await session.logout();
  await router.replace('/login');
}
</script>

<template>
  <div class="admin-shell">
    <button
      class="mobile-menu"
      type="button"
      aria-label="打开导航"
      title="打开导航"
      @click="mobileOpen = true"
    >
      <Menu :size="20" />
    </button>
    <div v-if="mobileOpen" class="nav-backdrop" @click="mobileOpen = false"></div>
    <aside class="sidebar" :class="{ open: mobileOpen }">
      <div class="product">
        <span class="product-icon"><ShieldCheck :size="23" /></span>
        <span><strong>X-ray</strong><small>管理平台</small></span>
        <button
          class="close-menu"
          type="button"
          aria-label="关闭导航"
          @click="mobileOpen = false"
        >
          <X :size="19" />
        </button>
      </div>
      <nav aria-label="主导航">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          @click="mobileOpen = false"
        >
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <footer>
        <div class="admin-name">
          <span>当前管理员</span><strong>{{ session.username }}</strong>
        </div>
        <button type="button" title="退出登录" @click="logout">
          <LogOut :size="17" /><span>退出</span>
        </button>
      </footer>
    </aside>
    <main class="workspace"><RouterView /></main>
  </div>
</template>

<style scoped>
.admin-shell { min-height: 100vh; background: var(--x-bg); }
.sidebar { position: fixed; inset: 0 auto 0 0; z-index: 20; width: 232px; display: flex; flex-direction: column; color: #e9f0f3; background: var(--x-nav); }
.product { height: 74px; display: flex; align-items: center; gap: 11px; padding: 0 20px; border-bottom: 1px solid rgb(255 255 255 / 9%); }
.product-icon { width: 36px; height: 36px; display: grid; place-items: center; color: white; background: var(--x-accent); border-radius: 5px; }
.product strong, .product small { display: block; letter-spacing: 0; }
.product strong { font-size: 16px; }
.product small { margin-top: 1px; color: #9eb0b8; font-size: 11px; }
nav { display: grid; gap: 3px; padding: 18px 12px; }
nav a { height: 40px; display: flex; align-items: center; gap: 12px; padding: 0 12px; border-radius: 5px; color: #b9c7cd; text-decoration: none; font-size: 13px; }
nav a:hover { color: white; background: rgb(255 255 255 / 5%); }
nav a.router-link-active { color: white; background: var(--x-nav-active); box-shadow: inset 3px 0 var(--x-accent); }
footer { margin-top: auto; padding: 16px; border-top: 1px solid rgb(255 255 255 / 9%); }
.admin-name span, .admin-name strong { display: block; }
.admin-name span { color: #7f959f; font-size: 11px; }
.admin-name strong { margin-top: 3px; overflow: hidden; font-size: 13px; text-overflow: ellipsis; }
footer button { width: 100%; height: 36px; display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 13px; border: 1px solid rgb(255 255 255 / 14%); border-radius: 5px; color: #c6d2d7; background: transparent; cursor: pointer; }
.workspace { min-height: 100vh; margin-left: 232px; padding: 30px 34px 50px; }
.mobile-menu, .close-menu { display: none; }
@media (max-width: 840px) {
  .workspace { margin-left: 0; padding: 74px 18px 36px; }
  .sidebar { transform: translateX(-100%); transition: transform .18s ease; }
  .sidebar.open { transform: translateX(0); }
  .mobile-menu { position: fixed; z-index: 15; top: 16px; left: 18px; width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid var(--x-border); border-radius: 5px; color: var(--x-text); background: white; }
  .close-menu { display: grid; place-items: center; margin-left: auto; border: 0; color: #b9c7cd; background: transparent; }
  .nav-backdrop { position: fixed; z-index: 19; inset: 0; background: rgb(13 22 27 / 46%); }
}
</style>
