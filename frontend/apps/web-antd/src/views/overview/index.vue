<script setup lang="ts">
import { Page } from '@vben/common-ui';

import { Card, Col, List, ListItem, Row, Space, Statistic } from 'ant-design-vue';

import { resourcesApi } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.overview);
const countLabels: Record<string, string> = {
  cloud_accounts: '云账号',
  node_pools: '节点池',
  nodes: '节点',
  operations_active: '进行中操作',
  access_profiles: '访问配置',
  subscriptions: '订阅',
};
</script>

<template>
  <Page title="总览" description="控制面当前状态">
    <template #title>
      <h1 class="mb-2 text-lg font-semibold">总览</h1>
    </template>
    <PageState :loading="loading" :error="error" @retry="reload">
      <Space direction="vertical" size="middle" class="w-full">
        <Card :bordered="false">
          <Space>
            <span>安全屏障</span>
            <StatusBadge :value="data?.security_mode" />
          </Space>
        </Card>
        <Row :gutter="[16, 16]" aria-label="资源数量">
          <Col v-for="(value, key) in data?.counts" :key="key" :xs="12" :md="8" :xl="4">
            <Card :bordered="false">
              <Statistic :title="countLabels[key] || key" :value="value" />
            </Card>
          </Col>
        </Row>
        <Row :gutter="[16, 16]">
          <Col :xs="24" :lg="12">
            <Card title="最近操作" :bordered="false">
              <PageState :empty="!data?.recent_operations?.length" empty-text="暂无操作">
                <List>
                  <ListItem v-for="item in data?.recent_operations" :key="String(item.id)">
                    <RouterLink :to="`/operations/${item.id}`">{{ item.kind }}</RouterLink>
                    <template #extra><StatusBadge :value="String(item.status)" /></template>
                  </ListItem>
                </List>
              </PageState>
            </Card>
          </Col>
          <Col :xs="24" :lg="12">
            <Card title="最近审计" :bordered="false">
              <PageState :empty="!data?.recent_audit?.length" empty-text="暂无审计">
                <List>
                  <ListItem v-for="item in data?.recent_audit" :key="String(item.id)">
                    <span>{{ item.action }}</span>
                    <template #extra><StatusBadge :value="String(item.result)" /></template>
                  </ListItem>
                </List>
              </PageState>
            </Card>
          </Col>
        </Row>
      </Space>
    </PageState>
  </Page>
</template>
