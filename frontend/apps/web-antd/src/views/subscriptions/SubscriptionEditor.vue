<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { Alert, Button, Form, Input, Modal, Table, Tabs } from 'ant-design-vue';

import { resourcesApi, type SecretDelivery, type SubscriptionDetail } from '@/api/resources';

const props = defineProps<{ open: boolean; subscriptionId?: string }>();
const emit = defineEmits<{ close: []; saved: []; delivery: [value: SecretDelivery] }>();
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const detail = ref<SubscriptionDetail>();
const tab = ref('profile');
const profileId = ref('');
const currentSubscriptionId = ref('');
const form = reactive({ name: '' });
const createKey = ref('');

watch(() => props.open, async (open) => {
  if (!open) return;
  error.value = '';
  loading.value = true;
  tab.value = 'profile';
  detail.value = undefined;
  profileId.value = '';
  currentSubscriptionId.value = '';
  createKey.value = crypto.randomUUID();
  Object.assign(form, { name: '' });
  try {
    if (props.subscriptionId) {
      detail.value = await resourcesApi.subscriptionDetail(props.subscriptionId);
      const profile = detail.value.profile;
      profileId.value = profile.id;
      currentSubscriptionId.value = detail.value.id;
      form.name = profile.name;
    }
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '加载失败';
  } finally {
    loading.value = false;
  }
});

async function save() {
  if (saving.value) return;
  saving.value = true;
  error.value = '';
  try {
    const name = form.name.trim();
    if (!name) throw new Error('请输入名称');
    const payload = { name };
    if (profileId.value) {
      await resourcesApi.updateAccessProfile(profileId.value, payload);
    } else {
      profileId.value = (await resourcesApi.createAccessProfile(payload, createKey.value)).id;
    }
    if (!currentSubscriptionId.value) {
      const issued = await resourcesApi.issueSubscription(profileId.value);
      currentSubscriptionId.value = issued.subscription_id;
      emit('delivery', issued);
    }
    emit('saved');
    emit('close');
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '保存失败';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal
    :open="open"
    :title="currentSubscriptionId ? '管理订阅' : '创建订阅'"
    :width="720"
    :footer="null"
    :confirm-loading="saving"
    :mask-closable="false"
    @cancel="!saving && emit('close')"
  >
    <Alert v-if="error" type="error" show-icon :message="error" class="mb-4" role="alert" />
    <Tabs v-model:active-key="tab">
      <Tabs.TabPane key="profile" tab="订阅">
        <Form layout="vertical" :model="form" @finish="save">
          <Form.Item label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
            <Input v-model:value="form.name" :disabled="loading" />
          </Form.Item>
          <Alert
            type="info"
            show-icon
            message="订阅默认包含全部已发布协议，不设置套餐、流量或到期限制；Token 由系统随机生成并仅交付一次。"
            class="mb-4"
          />
          <Button type="primary" html-type="submit" :loading="saving" :disabled="loading">
            保存订阅
          </Button>
        </Form>
      </Tabs.TabPane>
      <Tabs.TabPane v-if="detail" key="history" tab="发布历史">
        <Table
          :data-source="detail.assignments"
          row-key="protocol_id"
          :pagination="false"
          :columns="[
            { title: '协议', dataIndex: 'protocol' },
            { title: '目标代数', dataIndex: 'desired_generation' },
            { title: '已下发代数', dataIndex: 'applied_generation' },
            { title: '已确认', dataIndex: 'ready' },
          ]"
        />
        <Table
          class="mt-4"
          :data-source="detail.revisions"
          row-key="number"
          :pagination="false"
          :columns="[
            { title: '版本', dataIndex: 'number' },
            { title: '发布时间', dataIndex: 'published_at' },
            { title: '可用', dataIndex: 'usable' },
            { title: '格式', dataIndex: 'formats' },
          ]"
        />
      </Tabs.TabPane>
    </Tabs>
  </Modal>
</template>
