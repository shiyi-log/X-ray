<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { Plus, RefreshCw } from 'lucide-vue-next';

import { resourcesApi, type Capability, type CloudAccount } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.cloudAccounts);
const createOpen = ref(false);
const saving = ref(false);
const formError = ref('');
const capabilityAccount = ref<CloudAccount | null>(null);
const capabilityRows = ref<Capability[]>([]);
const capabilityError = ref('');
const form = reactive({
  name: '',
  provider: 'aws_lightsail',
  region: '',
  accessKey: '',
  secretKey: '',
});
const empty = computed(() => !data.value?.items.length);

async function createAccount() {
  saving.value = true;
  formError.value = '';
  try {
    const credentials =
      form.provider === 'aws_lightsail'
        ? { access_key_id: form.accessKey, secret_access_key: form.secretKey }
        : { access_key_id: form.accessKey, access_key_secret: form.secretKey };
    await resourcesApi.createCloudAccount({
      name: form.name,
      provider: form.provider,
      region: form.region,
      credentials,
    });
    Object.assign(form, {
      name: '', provider: 'aws_lightsail', region: '', accessKey: '', secretKey: '',
    });
    createOpen.value = false;
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '创建失败';
  } finally {
    saving.value = false;
    form.accessKey = '';
    form.secretKey = '';
  }
}

async function showCapabilities(account: CloudAccount) {
  capabilityAccount.value = account;
  capabilityRows.value = [];
  capabilityError.value = '';
  try {
    capabilityRows.value = (await resourcesApi.capabilities(account.id)).items;
  } catch (caught) {
    capabilityError.value = caught instanceof Error ? caught.message : '能力加载失败';
  }
}
</script>

<template>
  <PageHeader title="云账号" subtitle="AWS Lightsail 与阿里云 SWAS">
    <template #actions>
      <button class="icon-button" title="刷新" aria-label="刷新" @click="reload">
        <RefreshCw :size="17" />
      </button>
      <button class="command" type="button" @click="createOpen = true">
        <Plus :size="17" />添加账号
      </button>
    </template>
  </PageHeader>
  <PageState
    :loading="loading"
    :error="error"
    :empty="empty"
    empty-text="暂无云账号"
    @retry="reload"
  >
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>名称</th><th>平台</th><th>外部账号</th><th>凭据版本</th><th>验证</th><th>状态</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="item in data?.items" :key="item.id">
            <td><strong>{{ item.name }}</strong></td>
            <td>{{ item.provider === 'aws_lightsail' ? 'AWS Lightsail' : '阿里云 SWAS' }}</td>
            <td class="mono">{{ item.external_account_id }}</td>
            <td>v{{ item.credential_version }}</td>
            <td><StatusBadge :value="item.last_validation_code || 'UNVERIFIED'" /></td>
            <td><StatusBadge :value="item.enabled" /></td>
            <td><button class="link-button" @click="showCapabilities(item)">能力</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </PageState>
  <a-modal
    v-model:open="createOpen"
    title="添加云账号"
    :footer="null"
    :mask-closable="!saving"
    @after-close="form.secretKey = ''"
  >
    <form class="dialog-form" @submit.prevent="createAccount">
      <div v-if="formError" class="form-error">{{ formError }}</div>
      <label>名称<input v-model="form.name" required /></label>
      <label>平台<select v-model="form.provider"><option value="aws_lightsail">AWS Lightsail</option><option value="aliyun_swas">阿里云 SWAS</option></select></label>
      <label>区域<input v-model="form.region" required /></label>
      <label>Access Key<input v-model="form.accessKey" autocomplete="off" required /></label>
      <label>Secret Key<input v-model="form.secretKey" type="password" autocomplete="new-password" required /></label>
      <button class="command" type="submit" :disabled="saving">
        {{ saving ? '验证中' : '验证并保存' }}
      </button>
    </form>
  </a-modal>
  <a-modal
    :open="Boolean(capabilityAccount)"
    title="能力矩阵"
    :footer="null"
    @cancel="capabilityAccount = null"
  >
    <div v-if="capabilityError" class="form-error">{{ capabilityError }}</div>
    <table v-else class="capability-table">
      <thead><tr><th>能力</th><th>状态</th><th>说明</th></tr></thead>
      <tbody>
        <tr v-for="item in capabilityRows" :key="item.name">
          <td>{{ item.name }}</td><td><StatusBadge :value="item.status" /></td><td>{{ item.reason || '-' }}</td>
        </tr>
      </tbody>
    </table>
  </a-modal>
</template>

<style scoped src="../styles/resource-page.css"></style>
