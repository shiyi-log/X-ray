<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { Plus, RefreshCw } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import {
  Alert, Button, Card, Form, Input, InputNumber, Modal, Space, Table,
} from 'ant-design-vue';

import { resourcesApi, type NodePool } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const FormItem = Form.Item;
const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '额度', dataIndex: 'quota', key: 'quota' },
  { title: '占用', dataIndex: 'used', key: 'used' },
  { title: '可用', dataIndex: 'available', key: 'available' },
  { title: '允许创建', dataIndex: 'allow_create', key: 'allow_create' },
  { title: '操作', key: 'actions' },
];

const { data, loading, error, reload } = useResource(resourcesApi.nodePools);
const open = ref(false);
const saving = ref(false);
const formError = ref('');
const form = reactive({ name: '', quota: 3 });
const empty = computed(() => !data.value?.items.length);

async function createPool() {
  if (saving.value) return;
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
  <Page title="节点池" description="配额包含未确认释放的资源">
    <template #title><h1 class="mb-2 text-lg font-semibold">节点池</h1></template>
    <template #extra>
      <Space>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button type="primary" @click="open = true">
          <template #icon><Plus :size="16" /></template>
          新建节点池
        </Button>
      </Space>
    </template>
    <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
    <Card>
      <PageState
        :loading="loading"
        :error="error"
        :empty="empty"
        empty-text="暂无节点池"
        @retry="reload"
      >
        <Table :columns="columns" :data-source="data?.items || []" :pagination="false" :scroll="{ x: 'max-content' }" row-key="id">
          <template #bodyCell="{ column, record }">
            <div v-if="column.key === 'name'">
              <strong>{{ record.name }}</strong>
              <div class="text-xs text-muted-foreground">{{ record.id }}</div>
            </div>
            <StatusBadge v-else-if="column.key === 'allow_create'" :value="record.allow_create" />
            <Button v-else-if="column.key === 'actions'" type="link" @click="toggle(record as NodePool)">
              {{ record.allow_create ? '暂停创建' : '恢复创建' }}
            </Button>
          </template>
        </Table>
      </PageState>
    </Card>
    <Modal v-model:open="open" title="新建节点池" :footer="null">
      <Form :model="form" layout="vertical" @finish="createPool">
        <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
        <FormItem label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
          <Input v-model:value="form.name" />
        </FormItem>
        <FormItem label="配额" name="quota" :rules="[{ required: true, type: 'number', min: 1, message: '配额至少为 1' }]">
          <InputNumber v-model:value="form.quota" :min="1" :precision="0" class="w-full" />
        </FormItem>
        <Button type="primary" html-type="submit" :loading="saving" block>{{ saving ? '保存中' : '创建' }}</Button>
      </Form>
    </Modal>
  </Page>
</template>
