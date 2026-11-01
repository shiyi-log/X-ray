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
export type SystemInfo = components['schemas']['SystemInfo'] & {
  provider_identity_network: {
    enabled: boolean;
    source: ProviderIdentityChecksNetworkSource;
  };
};
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
  'ap-southeast-1',
  'ap-northeast-1',
  'ap-east-1',
  'us-east-1',
  'us-west-2',
] as const;

const json = (method: string, body?: unknown, headers?: HeadersInit): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
  headers,
});

export const resourcesApi = {
  overview: () => apiRequest<Overview>('/api/v1/overview'),
  system: () => apiRequest<SystemInfo>('/api/v1/system'),
  updateSystem: (payload: { provider_identity_network_enabled: boolean }) =>
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
    action: 'start' | 'reboot' | 'delete',
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
