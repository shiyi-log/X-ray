<script lang="ts" setup>
import { computed } from 'vue';
import { useRouter } from 'vue-router';

import { BasicLayout, UserDropdown } from '@vben/layouts';
import { preferences } from '@vben/preferences';
import { useUserStore } from '@vben/stores';

import { useSessionStore } from '@/stores/session';

const session = useSessionStore();
const router = useRouter();
const userStore = useUserStore();
const username = computed(
  () => session.username || userStore.userInfo?.username || 'admin',
);
const avatar = computed(() => preferences.app.defaultAvatar);

async function handleLogout() {
  try {
    await session.logout();
  } finally {
    await router.replace('/login');
  }
}
</script>

<template>
  <BasicLayout @clear-preferences-and-logout="handleLogout">
    <template #user-dropdown>
      <UserDropdown
        :avatar="avatar"
        :description="'X-ray Manager'"
        :text="username"
        @clear-preferences-and-logout="handleLogout"
        @logout="handleLogout"
      />
    </template>
  </BasicLayout>
</template>
