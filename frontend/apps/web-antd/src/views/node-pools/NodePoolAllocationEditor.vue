<script setup lang="ts">
import { reactive, ref, useId, watch } from 'vue';
import { Alert, Button, Form, InputNumber, Modal, Space, Switch } from 'ant-design-vue';

import { regionLabel, resourcesApi, SUPPORTED_REGIONS, type NodePool } from '@/api/resources';

const props = defineProps<{ open: boolean; pool: NodePool | null }>();
const emit = defineEmits<{
  'update:open': [value: boolean];
  saved: [];
}>();

const FormItem = Form.Item;
const formId = useId();
interface AllocationDraft {
  region: string;
  quota: number;
  historical?: boolean;
}

const form = reactive<{ allocations: AllocationDraft[]; allowCreate: boolean }>({
  allocations: [],
  allowCreate: true,
});
const saving = ref(false);
const error = ref('');

function seedForm(pool: NodePool | null) {
  const configured = pool?.allocations?.length
    ? pool.allocations
    : pool ? [{ region: pool.region, quota: pool.quota }] : [];
  const configuredByRegion = new Map(configured.map((item) => [item.region, item.quota]));
  const supported = new Set<string>(SUPPORTED_REGIONS);
  const allocations = [
    ...SUPPORTED_REGIONS.map((region) => ({
      region,
      quota: configuredByRegion.get(region) ?? 0,
    })),
    ...configured
      .filter((item) => !supported.has(item.region))
      .map((item) => ({ region: item.region, quota: item.quota, historical: true })),
  ];
  form.allocations.splice(0, form.allocations.length, ...allocations);
  form.allowCreate = pool?.allow_create ?? true;
  error.value = '';
}

watch(() => props.open, (open) => {
  if (open) seedForm(props.pool);
  else error.value = '';
});

async function save() {
  if (saving.value) return;
  const allocations = form.allocations.map(({ region, quota }) => ({
    region,
    quota: Number(quota),
  }));
  if (
    allocations.some((item) => !Number.isInteger(item.quota) || item.quota < 0)
    || new Set(allocations.map((item) => item.region)).size !== allocations.length
  ) {
    error.value = '请为每个地区填写唯一的非负整数额度';
    return;
  }
  saving.value = true;
  error.value = '';
  try {
    if (props.pool?.id) {
      await resourcesApi.updateNodePool(props.pool.id, {
        allocations,
        allow_create: form.allowCreate,
      });
    } else {
      await resourcesApi.createNodePool({
        allocations,
        allow_create: form.allowCreate,
      });
    }
    emit('update:open', false);
    emit('saved');
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '保存失败';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal
    :open="props.open"
    title="地区分配"
    :width="1100"
    :style="{ maxWidth: 'calc(100vw - 32px)' }"
    centered
    :body-style="{ maxHeight: 'calc(100dvh - 220px)', overflowY: 'auto' }"
    :closable="!saving"
    :mask-closable="!saving"
    :keyboard="!saving"
    @cancel="emit('update:open', false)"
  >
    <Form :id="formId" :model="form" layout="vertical" @finish="save">
      <Alert v-if="error" class="mb-4" :message="error" type="error" show-icon />
      <FormItem label="地区额度" required>
        <a
          class="mb-3 inline-block text-sm"
          href="https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-regions-and-availability-zones-in-amazon-lightsail.html"
          target="_blank"
          rel="noreferrer"
        >AWS Lightsail 支持地区</a>
        <div class="allocation-grid">
          <div v-for="allocation in form.allocations" :key="allocation.region" class="allocation-item">
            <span class="min-w-0">{{ regionLabel(allocation.region) }}{{ allocation.historical ? '（历史地区）' : '' }}</span>
            <InputNumber
              v-model:value="allocation.quota"
              :min="0"
              :precision="0"
              class="w-full"
              :aria-label="`${allocation.region}额度`"
            />
          </div>
        </div>
      </FormItem>
      <FormItem label="允许创建服务器">
        <Space>
          <Switch
            v-model:checked="form.allowCreate"
            aria-label="允许创建服务器"
            checked-children="开"
            un-checked-children="关"
          />
          <span>{{ form.allowCreate ? '新服务器按已分配额度创建' : '已禁止创建新服务器' }}</span>
        </Space>
      </FormItem>
      <Alert
        v-if="!form.allowCreate"
        class="mb-4"
        type="warning"
        show-icon
        message="关闭后，服务端会拒绝新的服务器创建；现有服务器不受影响。"
      />
    </Form>
    <template #footer>
      <Button :disabled="saving" @click="emit('update:open', false)">取消</Button>
      <Button type="primary" html-type="submit" :form="formId" :loading="saving">
        {{ saving ? '保存中' : '保存' }}
      </Button>
    </template>
  </Modal>
</template>

<style scoped>
.allocation-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px 24px;
}

.allocation-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 76px;
  align-items: center;
  gap: 12px;
}

@media (max-width: 900px) {
  .allocation-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .allocation-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
