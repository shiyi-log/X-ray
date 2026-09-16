<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>();
</script>

<template>
  <header class="page-header">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-header { min-height: 74px; display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 0 0 20px; border-bottom: 1px solid var(--x-border); }
h1 { margin: 0; font-size: 22px; line-height: 1.35; font-weight: 650; }
p { margin: 5px 0 0; color: var(--x-text-muted); font-size: 13px; }
.page-actions { display: flex; align-items: center; gap: 8px; }
@media (max-width: 720px) { .page-header { min-height: 0; flex-direction: column; gap: 14px; } .page-actions { width: 100%; } }
</style>
