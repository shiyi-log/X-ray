import type { components } from './generated/schema';
import { apiRequest } from './request';

export type CloudAccount = components['schemas']['CloudAccount'];
export interface NodePoolAllocation {
  region: string;
  quota: number;
  used?: number;
  available?: number;
}
export type NodePool = Omit<
  components['schemas']['NodePool'],
  'allocations' | 'region' | 'regions'
> & {
  allocations?: readonly NodePoolAllocation[];
  allow_create?: boolean;
  region: string;
  regions?: readonly string[];
};
export type NodeAddress = string | {
  address?: string;
  family?: number;
  ip?: string;
  ip_address?: string;
  kind?: string;
  resource_id?: string;
  type?: string;
  value?: string;
};
export type ManagedNode = Omit<components['schemas']['ManagedNode'], 'addresses' | 'pool_id' | 'pool_name'> & {
  addresses?: readonly NodeAddress[];
  traffic_download_bytes?: number;
  traffic_sampled_at?: string | null;
  traffic_state?: 'NO_DATA' | 'COLLECTED' | string;
  traffic_total_bytes?: number;
  traffic_upload_bytes?: number;
};
export type Operation = components['schemas']['Operation'];
export interface ProfilePolicy {
  plan_id: string | null; expires_at: string | null; traffic_limit_bytes: number | null;
  upload_bytes: number; download_bytes: number; usage_updated_at: string | null;
  entitlement_state: string;
}
export type AccessProfile = components['schemas']['AccessProfile'] & Partial<ProfilePolicy>;
export type Subscription = components['schemas']['Subscription'] & {
  policy?: ProfilePolicy;
  current_token_status?: 'ACTIVE' | 'REVOKED' | 'EXPIRED' | null;
};
export interface SubscriptionDetail extends Subscription {
  profile: AccessProfile;
  assignments: { protocol_id: string; node_id: string; protocol: string; desired_generation: number; applied_generation: number; ready: boolean }[];
  revisions: { number: number; published_at: string; usable: boolean; formats: string[] }[];
}
export type SubscriptionToken = components['schemas']['SubscriptionToken'];
export type AuditEvent = components['schemas']['AuditEvent'];
export type Overview = components['schemas']['Overview'];
export type ProviderIdentityChecksNetworkSource = 'DATABASE' | 'ENVIRONMENT';
export type NodeAutomationSettingSource = 'DATABASE' | 'DEFAULT';
export interface NodePoolCreationTemplate {
  region: string;
  cloud_account_id: string;
  plan_id: string;
  image_id: string;
}
export type SystemInfo = components['schemas']['SystemInfo'] & {
  provider_identity_network: {
    enabled: boolean;
    source: ProviderIdentityChecksNetworkSource;
  };
  node_status_sync: {
    enabled: boolean;
    interval_minutes: number;
    last_scheduled_at: string | null;
    source: 'DATABASE' | 'DEFAULT';
  };
  node_pool_sync: {
    enabled: boolean;
    interval_minutes: number;
    creation_templates: NodePoolCreationTemplate[];
    last_scheduled_at: string | null;
    source: NodeAutomationSettingSource;
  };
  node_daily_restart: {
    enabled: boolean;
    time: string;
    timezone: string;
    last_scheduled_at: string | null;
    source: NodeAutomationSettingSource;
  };
  usage_sync: {
    enabled: boolean;
    interval_minutes: number;
    last_scheduled_at: string | null;
    source: NodeAutomationSettingSource;
  };
};
export interface SystemUpgradeJob {
  id: string;
  version: string;
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  phase: string;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}
export interface SystemUpgradeInfo {
  current_version: string;
  available: boolean;
  reason: string | null;
  candidates: { version: string; published_at: string; notes: string }[];
  jobs: SystemUpgradeJob[];
}
export type ActionPreview = components['schemas']['ActionPreview'];
export type SecretDelivery = components['schemas']['SecretDelivery'];

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface OperationAccepted {
  operation_id: string;
  status: string;
  target_type: string;
  target_id: string;
  link_revoked?: boolean;
}

export interface Capability {
  name: string;
  status: 'SUPPORTED' | 'UNSUPPORTED' | 'UNVERIFIED';
  regions: string[];
  plans: string[];
  reason: string;
  checked_at: string;
  live_verified: boolean;
}

/** Regions accepted by the node creation API. */
export const SUPPORTED_REGIONS = [
  'ap-east-1',
  'ap-northeast-1',
  'ap-northeast-2',
  'ap-south-1',
  'ap-southeast-1',
  'ap-southeast-2',
  'ap-southeast-3',
  'ap-southeast-5',
  'ca-central-1',
  'eu-central-1',
  'eu-north-1',
  'eu-south-2',
  'eu-west-1',
  'eu-west-2',
  'eu-west-3',
  'sa-east-1',
  'us-east-1',
  'us-east-2',
  'us-west-2',
] as const;

export const AWS_LIGHTSAIL_REGION_LABELS: Record<(typeof SUPPORTED_REGIONS)[number], string> = {
  'ap-east-1': '香港',
  'ap-northeast-1': '东京',
  'ap-northeast-2': '首尔',
  'ap-south-1': '孟买',
  'ap-southeast-1': '新加坡',
  'ap-southeast-2': '悉尼',
  'ap-southeast-3': '雅加达',
  'ap-southeast-5': '马来西亚',
  'ca-central-1': '加拿大中部',
  'eu-central-1': '法兰克福',
  'eu-north-1': '斯德哥尔摩',
  'eu-south-2': '西班牙',
  'eu-west-1': '爱尔兰',
  'eu-west-2': '伦敦',
  'eu-west-3': '巴黎',
  'sa-east-1': '圣保罗',
  'us-east-1': '北弗吉尼亚',
  'us-east-2': '俄亥俄',
  'us-west-2': '俄勒冈',
};

export function regionLabel(region: string) {
  const label = AWS_LIGHTSAIL_REGION_LABELS[region as keyof typeof AWS_LIGHTSAIL_REGION_LABELS];
  if (label) return `${label}（${region}）`;
  const aliRegionLabels: Record<string, string> = {
    'af-south-1': '非洲（南非）',
    'cn-beijing': '中国北京',
    'cn-chengdu': '中国成都',
    'cn-hangzhou': '中国杭州',
    'cn-hongkong': '中国香港',
    'cn-shanghai': '中国上海',
    'cn-shenzhen': '中国深圳',
    'cn-zhangjiakou': '中国张家口',
  };
  return aliRegionLabels[region] ? `${aliRegionLabels[region]}（${region}）` : region;
}

const json = (method: string, body?: unknown, headers?: HeadersInit): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
  headers,
});

export const resourcesApi = {
  overview: () => apiRequest<Overview>('/api/v1/overview'),
  system: () => apiRequest<SystemInfo>('/api/v1/system'),
  systemUpgrade: () => apiRequest<SystemUpgradeInfo>('/api/v1/system/upgrade/'),
  startSystemUpgrade: (payload: { version: string; confirmation: string }, idempotencyKey: string) =>
    apiRequest<SystemUpgradeJob>(
      '/api/v1/system/upgrade/',
      json('POST', payload, { 'Idempotency-Key': idempotencyKey }),
    ),
  updateSystem: (payload: {
    provider_identity_network_enabled?: boolean;
    node_status_sync_enabled?: boolean;
    node_status_sync_interval_minutes?: number;
    node_pool_sync_enabled?: boolean;
    node_pool_sync_interval_minutes?: number;
    node_pool_sync_creation_templates?: NodePoolCreationTemplate[];
    node_daily_restart_enabled?: boolean;
    node_daily_restart_time?: string;
    node_daily_restart_timezone?: string;
    usage_sync_enabled?: boolean;
    usage_sync_interval_minutes?: number;
  }) =>
    apiRequest<SystemInfo>('/api/v1/system', json('PATCH', payload)),
  cloudAccounts: () => apiRequest<Page<CloudAccount>>('/api/v1/cloud-accounts/'),
  createCloudAccount: (payload: Record<string, unknown>) =>
    apiRequest<CloudAccount>('/api/v1/cloud-accounts/', json('POST', payload)),
  updateCloudAccount: (id: string, payload: { enabled: boolean }) =>
    apiRequest<CloudAccount>(`/api/v1/cloud-accounts/${id}/`, json('PATCH', payload)),
  capabilities: (id: string) =>
    apiRequest<{ items: Capability[] }>(`/api/v1/cloud-accounts/${id}/capabilities/`),
  nodePools: () => apiRequest<Page<NodePool>>('/api/v1/node-pools/'),
  createNodePool: (payload: {
    allocations: { region: string; quota: number }[];
    allow_create?: boolean;
  }) =>
    apiRequest<NodePool>('/api/v1/node-pools/', json('POST', payload)),
  updateNodePool: (id: string, payload: {
    allocations: { region: string; quota: number }[];
    allow_create?: boolean;
  }) =>
    apiRequest<NodePool>(`/api/v1/node-pools/${id}/`, json('PATCH', payload)),
  nodes: (page = 1, pageSize = 25) =>
    apiRequest<Page<ManagedNode>>(`/api/v1/nodes/?page=${page}&page_size=${pageSize}`),
  nodeDetail: (id: string) => apiRequest<ManagedNode>(`/api/v1/nodes/${id}/`),
  refreshNodeStatus: (id: string, idempotencyKey: string = crypto.randomUUID()) =>
    apiRequest<OperationAccepted>(
      `/api/v1/nodes/${id}/refresh/`,
      json('POST', {}, { 'Idempotency-Key': idempotencyKey }),
    ),
  nodeAction: (
    id: string,
    action: 'start' | 'stop' | 'reboot' | 'delete',
    payload: { preview_id?: string; confirmation?: string } = {},
    idempotencyKey: string = crypto.randomUUID(),
  ) =>
    apiRequest<OperationAccepted>(
      `/api/v1/nodes/${id}/actions/${action}/`,
      json('POST', payload, { 'Idempotency-Key': idempotencyKey }),
    ),
  createNode: (payload: Record<string, unknown>, idempotencyKey: string) =>
    apiRequest<OperationAccepted>(
      '/api/v1/nodes/',
      json('POST', payload, { 'Idempotency-Key': idempotencyKey }),
    ),
  operations: () => apiRequest<Page<Operation>>('/api/v1/operations/'),
  operation: (id: string) => apiRequest<Operation>(`/api/v1/operations/${id}/`),
  cancelOperation: (id: string) =>
    apiRequest<Operation>(`/api/v1/operations/${id}/cancel/`, json('POST', {})),
  retryOperation: (id: string) =>
    apiRequest<Operation>(`/api/v1/operations/${id}/retry/`, json('POST', {})),
  accessProfiles: (page = 1, pageSize = 25) =>
    apiRequest<Page<AccessProfile>>(`/api/v1/access-profiles/?page=${page}&page_size=${pageSize}`),
  createAccessProfile: (value: string | Record<string, unknown>, key: string = crypto.randomUUID()) =>
    apiRequest<AccessProfile>('/api/v1/access-profiles/', json('POST', typeof value === 'string' ? { name: value } : value, { 'Idempotency-Key': key })),
  updateAccessProfile: (id: string, payload: Record<string, unknown>, key: string = crypto.randomUUID()) =>
    apiRequest<AccessProfile>(`/api/v1/access-profiles/${id}/`, json('PATCH', payload, { 'Idempotency-Key': key })),
  subscriptionDetail: (id: string) => apiRequest<SubscriptionDetail>(`/api/v1/subscriptions/${id}/`),
  subscriptionTokens: (subscriptionId: string, page = 1, pageSize = 25) =>
    apiRequest<Page<SubscriptionToken>>(
      `/api/v1/subscriptions/${subscriptionId}/tokens/?page=${page}&page_size=${pageSize}`,
    ),
  revokeSubscriptionToken: (
    subscriptionId: string,
    tokenId: string,
    payload: { preview_id: string; confirmation: string },
    idempotencyKey: string,
  ) =>
    apiRequest<SubscriptionToken>(
      `/api/v1/subscriptions/${subscriptionId}/tokens/${tokenId}/revoke/`,
      json('POST', payload, { 'Idempotency-Key': idempotencyKey }),
    ),
  subscriptions: (page = 1, q = '') => apiRequest<Page<Subscription>>(`/api/v1/subscriptions/?page=${page}&q=${encodeURIComponent(q)}`),
  auditEvents: () => apiRequest<Page<AuditEvent>>('/api/v1/audit-events/'),
  createPreview: (payload: Record<string, unknown>) =>
    apiRequest<ActionPreview>('/api/v1/operations/previews/', json('POST', payload)),
  issueSubscription: (profileId: string) =>
    apiRequest<SecretDelivery>(
      `/api/v1/access-profiles/${profileId}/subscription/`,
      json('POST', {}, { 'Idempotency-Key': crypto.randomUUID() }),
    ),
  rotateSubscription: (subscriptionId: string) =>
    apiRequest<SecretDelivery>(
      `/api/v1/subscriptions/${subscriptionId}/rotate/`,
      json('POST', {}, { 'Idempotency-Key': crypto.randomUUID() }),
    ),
  publishSubscription: (subscriptionId: string) =>
    apiRequest<Subscription>(
      `/api/v1/subscriptions/${subscriptionId}/publish/`,
      json('POST', {}, { 'Idempotency-Key': crypto.randomUUID() }),
    ),
  forceRevoke: (
    profileId: string,
    payload: { preview_id: string; confirmation: string },
    idempotencyKey: string,
  ) =>
    apiRequest<OperationAccepted>(
      `/api/v1/access-profiles/${profileId}/force-revoke/`,
      json('POST', payload, { 'Idempotency-Key': idempotencyKey }),
    ),
};
