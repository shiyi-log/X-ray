<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { Alert, Button, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tabs } from 'ant-design-vue';
import { resourcesApi, type ManagedNode, type ProtocolOption, type SecretDelivery, type SubscriptionDetail, type SubscriptionPlan } from '@/api/resources';

const props = defineProps<{ open: boolean; subscriptionId?: string }>();
const emit = defineEmits<{ close: []; saved: []; delivery: [value: SecretDelivery] }>();
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const detail = ref<SubscriptionDetail>();
const plans = ref<SubscriptionPlan[]>([]);
const catalog = ref<ProtocolOption[]>([]);
const nodes = ref<ManagedNode[]>([]);
const protocolForm = reactive({ node_id: '', protocol: 'vless', port: 18443, transport: 'tcp', tls_enabled: false, server_name: '', certificate_ref: '' });
async function loadNodes() { nodes.value = (await resourcesApi.nodes()).items.filter(n => n.desired_state === 'PRESENT' && n.security_state === 'OPEN'); }
async function saveProtocol() {
  saving.value = true; error.value = '';
  try {
    await resourcesApi.createSubscriptionProtocol({ ...protocolForm });
    catalog.value = (await resourcesApi.subscriptionCatalog()).items;
    tab.value = 'profile';
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '协议配置失败'; }
  finally { saving.value = false; }
}
const tab = ref('profile');
const profileId = ref('');
const currentSubscriptionId = ref('');
const form = reactive({ name: '', plan_id: undefined as string | undefined, expires_at: '', traffic_gib: undefined as number | undefined, protocol_ids: [] as string[] });
const planForm = reactive({ id: '', name: '', duration_days: undefined as number | undefined, traffic_gib: undefined as number | undefined, enabled: true });
const createKey = ref('');
const assignmentKey = ref('');

watch(() => props.open, async (open) => {
  if (!open) return;
  error.value = ''; loading.value = true; tab.value = 'profile'; detail.value = undefined;
  profileId.value = ''; currentSubscriptionId.value = ''; createKey.value = crypto.randomUUID(); assignmentKey.value = crypto.randomUUID();
  Object.assign(form, { name: '', plan_id: undefined, expires_at: '', traffic_gib: undefined, protocol_ids: [] });
  try {
    const [availablePlans, availableProtocols] = await Promise.all([resourcesApi.subscriptionPlans(), resourcesApi.subscriptionCatalog()]);
    plans.value = availablePlans.items; catalog.value = availableProtocols.items;
    if (props.subscriptionId) {
      detail.value = await resourcesApi.subscriptionDetail(props.subscriptionId);
      const p = detail.value.profile;
      profileId.value = p.id; currentSubscriptionId.value = detail.value.id;
      Object.assign(form, { name: p.name, plan_id: p.plan_id || undefined,
        expires_at: p.expires_at || '', traffic_gib: p.traffic_limit_bytes ? p.traffic_limit_bytes / 2 ** 30 : undefined,
        protocol_ids: [...new Set(detail.value.assignments.map((item) => item.protocol_id))] });
    }
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '加载失败'; }
  finally { loading.value = false; }
});

function choosePlan(id: unknown) {
  const plan = plans.value.find((item) => item.id === id);
  if (!plan) return;
  form.traffic_gib = plan.traffic_limit_bytes ? plan.traffic_limit_bytes / 2 ** 30 : undefined;
  form.expires_at = plan.duration_days ? new Date(Date.now() + plan.duration_days * 86400000).toISOString() : '';
}

async function save() {
  if (saving.value) return;
  saving.value = true; error.value = '';
  try {
    if (!form.name.trim()) throw new Error('请输入名称');
    if (form.expires_at && !/(Z|[+-]\d{2}:\d{2})$/i.test(form.expires_at)) throw new Error('到期时间必须包含时区');
    const parsed = form.expires_at ? new Date(form.expires_at) : null;
    if (parsed && Number.isNaN(parsed.getTime())) throw new Error('到期时间无效，请填写带时区的 ISO 时间');
    const payload = { name: form.name.trim(), plan_id: form.plan_id || null,
      traffic_limit_bytes: form.traffic_gib == null ? null : Math.round(form.traffic_gib * 2 ** 30),
      expires_at: parsed?.toISOString() || null };
    if (profileId.value) await resourcesApi.updateAccessProfile(profileId.value, payload);
    else profileId.value = (await resourcesApi.createAccessProfile(payload, createKey.value)).id;
    if (!currentSubscriptionId.value) {
      const issued = await resourcesApi.issueSubscription(profileId.value);
      currentSubscriptionId.value = issued.subscription_id;
      emit('delivery', issued);
    }
    await resourcesApi.assignSubscription(currentSubscriptionId.value, form.protocol_ids, assignmentKey.value);
    emit('saved'); emit('close');
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '保存失败'; }
  finally { saving.value = false; }
}

async function savePlan() {
  if (saving.value) return;
  saving.value = true; error.value = '';
  try {
    if (!planForm.name.trim()) throw new Error('请输入套餐名称');
    await resourcesApi.saveSubscriptionPlan({ name: planForm.name.trim(), duration_days: planForm.duration_days || null,
      traffic_limit_bytes: planForm.traffic_gib == null ? null : Math.round(planForm.traffic_gib * 2 ** 30), enabled: planForm.enabled }, planForm.id || undefined);
    plans.value = (await resourcesApi.subscriptionPlans()).items;
    Object.assign(planForm, { id: '', name: '', duration_days: undefined, traffic_gib: undefined, enabled: true });
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '套餐保存失败'; }
  finally { saving.value = false; }
}
function editPlan(plan: SubscriptionPlan) {
  Object.assign(planForm, { id: plan.id, name: plan.name, duration_days: plan.duration_days || undefined,
    traffic_gib: plan.traffic_limit_bytes ? plan.traffic_limit_bytes / 2 ** 30 : undefined, enabled: plan.enabled });
}
</script>

<template>
  <Modal :open="open" :title="currentSubscriptionId ? '管理订阅' : '创建订阅'" :width="850" :footer="null" :confirm-loading="saving" :mask-closable="false" @cancel="!saving && emit('close')">
    <Alert v-if="error" type="error" show-icon :message="error" class="mb-4" role="alert" />
    <Tabs v-model:active-key="tab">
      <Tabs.TabPane key="profile" tab="订阅与节点">
        <Form layout="vertical" :model="form" @finish="save">
          <Form.Item label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]"><Input v-model:value="form.name" :disabled="loading" /></Form.Item>
          <Form.Item label="套餐"><Select v-model:value="form.plan_id" allow-clear :options="plans.filter(p => p.enabled).map(p => ({ label: p.name, value: p.id }))" @change="choosePlan" /></Form.Item>
          <Form.Item label="流量额度（GiB，留空不限量）"><InputNumber v-model:value="form.traffic_gib" :min="0.001" :precision="3" /></Form.Item>
          <Form.Item label="到期时间（带时区 ISO 时间，留空不限期）"><Input v-model:value="form.expires_at" placeholder="2030-01-01T00:00:00+08:00" /></Form.Item>
          <Form.Item label="节点与协议"><Select v-model:value="form.protocol_ids" mode="multiple" :loading="loading" :options="catalog.map(p => ({ label: `${p.name} / ${p.protocol} / ${p.port} / ${p.state}`, value: p.id, disabled: !p.publishable_tls }))" placeholder="选择允许访问的节点协议" /></Form.Item>
          <Alert type="info" show-icon message="保存后等待节点配置下发成功，再发布订阅。取消节点会移除对应访问凭据。套餐调整不清零已采集流量。" class="mb-4" />
          <Alert v-if="!catalog.length && !loading" type="warning" message="暂无可分配协议，请先配置节点协议。仍可创建订阅，稍后分配。" class="mb-4" />
          <Button type="primary" html-type="submit" :loading="saving" :disabled="loading">保存订阅</Button>
        </Form>
      </Tabs.TabPane>
      <Tabs.TabPane key="plans" tab="套餐管理">
        <Form layout="vertical" @finish="savePlan">
          <Form.Item label="套餐名称"><Input v-model:value="planForm.name" /></Form.Item>
          <Space wrap>
            <Form.Item label="有效天数（留空不限期）"><InputNumber v-model:value="planForm.duration_days" :min="1" :max="36500" /></Form.Item>
            <Form.Item label="流量（GiB，留空不限量）"><InputNumber v-model:value="planForm.traffic_gib" :min="0.001" /></Form.Item>
            <Form.Item label="启用"><Switch v-model:checked="planForm.enabled" /></Form.Item>
          </Space>
          <Button html-type="submit" :loading="saving">{{ planForm.id ? '更新套餐' : '新增套餐' }}</Button>
        </Form>
        <Table class="mt-4" :data-source="plans" row-key="id" :pagination="false" :columns="[{title:'套餐', dataIndex:'name'}, {title:'天数', dataIndex:'duration_days'}, {title:'启用', dataIndex:'enabled'}, {title:'操作', key:'edit'}]">
          <template #bodyCell="{column, record}"><Button v-if="column.key === 'edit'" type="link" @click="editPlan(record as SubscriptionPlan)">编辑</Button></template>
        </Table>
      </Tabs.TabPane>
      <Tabs.TabPane key="protocols" tab="节点协议">
        <Button class="mb-4" @click="loadNodes">加载可用节点</Button>
        <Form layout="vertical" @finish="saveProtocol">
          <Form.Item label="节点"><Select v-model:value="protocolForm.node_id" :options="nodes.map(n => ({label: n.external_id || n.id, value: n.id}))" /></Form.Item>
          <Form.Item label="协议"><Select v-model:value="protocolForm.protocol" :options="['shadowsocks','socks5','vmess','vless','trojan'].map(p => ({label:p,value:p}))" /></Form.Item>
          <Form.Item label="端口"><InputNumber v-model:value="protocolForm.port" :min="1" :max="65535" /></Form.Item>
          <Form.Item label="传输"><Select v-model:value="protocolForm.transport" :options="(protocolForm.protocol === 'socks5' || protocolForm.protocol === 'shadowsocks' ? ['tcp'] : ['tcp','ws','grpc']).map(p => ({label:p,value:p}))" /></Form.Item>
          <Form.Item label="TLS"><Switch v-model:checked="protocolForm.tls_enabled" /></Form.Item>
          <template v-if="protocolForm.tls_enabled">
            <Form.Item label="服务器域名"><Input v-model:value="protocolForm.server_name" /></Form.Item>
            <Form.Item label="节点证书路径前缀"><Input v-model:value="protocolForm.certificate_ref" placeholder="/usr/local/etc/xray/certs/proxy（对应 .crt 和 .key）" /></Form.Item>
          </template>
          <Alert class="mb-4" type="info" message="先准备节点证书和所需防火墙规则。此处只登记协议；分配访问身份后才会下发，TLS 证书始终校验。" />
          <Button html-type="submit" :loading="saving">登记协议</Button>
        </Form>
      </Tabs.TabPane>
      <Tabs.TabPane v-if="detail" key="history" tab="下发状态与发布历史">
        <Table :data-source="detail.assignments" row-key="protocol_id" :pagination="false" :columns="[{title:'协议',dataIndex:'protocol'}, {title:'目标代数',dataIndex:'desired_generation'}, {title:'已下发代数',dataIndex:'applied_generation'}, {title:'已确认',dataIndex:'ready'}]" />
        <Table class="mt-4" :data-source="detail.revisions" row-key="number" :pagination="false" :columns="[{title:'版本',dataIndex:'number'}, {title:'发布时间',dataIndex:'published_at'}, {title:'可用',dataIndex:'usable'}, {title:'格式',dataIndex:'formats'}]" />
      </Tabs.TabPane>
    </Tabs>
  </Modal>
</template>
