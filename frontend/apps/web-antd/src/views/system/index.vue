<script setup lang="ts">
import { Page } from '@vben/common-ui';

import { Card, Descriptions, DescriptionsItem, Space, Tag } from 'ant-design-vue';

import { resourcesApi } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.system);
</script>

<template>
  <Page title="系统设置" description="部署配置只读">
    <template #title>
      <h1 class="mb-2 text-lg font-semibold">系统设置</h1>
    </template>
    <Card :bordered="false">
      <PageState :loading="loading" :error="error" @retry="reload">
        <Descriptions bordered :column="1">
          <DescriptionsItem label="版本">{{ data?.version }}</DescriptionsItem>
          <DescriptionsItem label="环境">{{ data?.environment }}</DescriptionsItem>
          <DescriptionsItem label="调试模式"><StatusBadge :value="data?.debug" /></DescriptionsItem>
          <DescriptionsItem label="管理 Host allowlist">
            <Space wrap>
              <Tag v-for="item in data?.allowed_hosts" :key="item">{{ item }}</Tag>
              <span v-if="!data?.allowed_hosts?.length">未配置</span>
            </Space>
          </DescriptionsItem>
          <DescriptionsItem label="CSRF 可信来源">
            <Space wrap>
              <Tag v-for="item in data?.csrf_trusted_origins" :key="item">{{ item }}</Tag>
              <span v-if="!data?.csrf_trusted_origins?.length">未配置</span>
            </Space>
          </DescriptionsItem>
        </Descriptions>
      </PageState>
    </Card>
  </Page>
</template>
