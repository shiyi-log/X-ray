<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { Plus, RefreshCw } from 'lucide-vue-next';

import { resourcesApi, type NodePool } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.nodePools);
const open = ref(false);
const saving = ref(false);
const formError = ref('');
const form = reactive({ name: '', quota: 3 });
const empty = computed(() => !data.value?.items.length);

async function createPool() {
  saving.value = true;
  formError.value = '';
  try {
    await resourcesApi.createNodePool(form);
    form.name = '';
    form.quota = 3;
    open.value = false;
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '创建失败';
  } finally {
    saving.value = false;
  }
}

async function toggle(item: NodePool) {
  try {
    await resourcesApi.updateNodePool(item.id, { allow_create: !item.allow_create });
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '保存失败';
  }
}
</script>

<template>
  <PageHeader title="节点池" subtitle="配额包含未确认释放的资源">
    <template #actions>
      <button class="icon-button" title="刷新" aria-label="刷新" @click="reload">
        <RefreshCw :size="17" />
      </button>
      <button class="command" @click="open = true"><Plus :size="17" />新建节点池</button>
    </template>
  </PageHeader>
  <div v-if="formError" class="page-error">{{ formError }}</div>
  <PageState
    :loading="loading"
    :error="error"
    :empty="empty"
    empty-text="暂无节点池"
    @retry="reload"
  >
    <div class="table-wrap">
      <table>
        <thead><tr><th>名称</th><th>额度</th><th>占用</th><th>可用</th><th>允许创建</th><th></th></tr></thead>
        <tbody><tr v-for="item in data?.items" :key="item.id"><td><strong>{{ item.name }}</strong><small class="resource-id">{{ item.id }}</small></td><td>{{ item.quota }}</td><td>{{ item.used }}</td><td>{{ item.available }}</td><td><StatusBadge :value="item.allow_create" /></td><td><button class="link-button" @click="toggle(item)">{{ item.allow_create ? '暂停创建' : '恢复创建' }}</button></td></tr></tbody>
      </table>
    </div>
  </PageState>
  <a-modal v-model:open="open" title="新建节点池" :footer="null">
    <form class="dialog-form" @submit.prevent="createPool">
      <div v-if="formError" class="form-error">{{ formError }}</div>
      <label>名称<input v-model="form.name" required /></label>
      <label>配额<input v-model.number="form.quota" type="number" min="1" required /></label>
      <button class="command" :disabled="saving">{{ saving ? '保存中' : '创建' }}</button>
    </form>
  </a-modal>
</template>

<style scoped src="../styles/resource-page.css"></style>
