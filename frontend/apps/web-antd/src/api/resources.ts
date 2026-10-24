import type { components } from './generated/schema';
import { apiRequest } from './request';

export type CloudAccount = components['schemas']['CloudAccount'];
export interface NodePoolAllocation {
  region: string;
  quota: number;
  used?: number;
  available?: number;
}
export type NodePool = components['schemas']['NodePool'] & {
  allocations?: readonly NodePoolAllocation[];
};
export type ManagedNode = components['schemas']['ManagedNode'];
export type Operation = components['schemas']['Operation'];
export interface ProfilePolicy {
  plan_id: string | null; expires_at: string | null; traffic_limit_bytes: number | null;
  upload_bytes: number; download_bytes: number; usage_updated_at: string | null;
  entitlement_state: string;
}
export type AccessProfile = components['schemas']['AccessProfile'] & Partial<ProfilePolicy>;
export type Subscription = components['schemas']['Subscription'] & { policy?: ProfilePolicy };
export interface SubscriptionPlan { id: string; name: string; duration_days: number | null; traffic_limit_bytes: number | null; enabled: boolean }
export interface ProtocolOption { id: string; node_id: string; name: string; protocol: string; port: number; transport: string; tls: boolean; state: string; publishable_tls: boolean }
export interface SubscriptionDetail extends Subscription {
  profile: AccessProfile;
  assignments: { protocol_id: string; node_id: string; protocol: string; desired_generation: number; applied_generation: number; ready: boolean }[];
  revisions: { number: number; published_at: string; usable: boolean; formats: string[] }[];
}
export type AuditEvent = components['schemas']['AuditEvent'];
export type Overview = components['schemas']['Overview'];
export type SystemInfo = components['schemas']['SystemInfo'];
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

/** Regions accepted by the node-pool allocation API. */
export const SUPPORTED_REGIONS = [
  'ap-southeast-1',
  'ap-northeast-1',
  'ap-east-1',
  'us-east-1',
  'us-west-2',
  'eu-west-1',
] as const;

const json = (method: string, body?: unknown, headers?: HeadersInit): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
  headers,
});

export const resourcesApi = {
  overview: () => apiRequest<Overview>('/api/v1/overview'),
  system: () => apiRequest<SystemInfo>('/api/v1/system'),
  cloudAccounts: () => apiRequest<Page<CloudAccount>>('/api/v1/cloud-accounts/'),
  createCloudAccount: (payload: Record<string, unknown>) =>
    apiRequest<CloudAccount>('/api/v1/cloud-accounts/', json('POST', payload)),
  capabilities: (id: string) =>
    apiRequest<{ items: Capability[] }>(`/api/v1/cloud-accounts/${id}/capabilities/`),
  nodePools: () => apiRequest<Page<NodePool>>('/api/v1/node-pools/'),
  createNodePool: (payload: {
    name: string;
    allocations: { region: string; quota: number }[];
  }) =>
    apiRequest<NodePool>('/api/v1/node-pools/', json('POST', payload)),
  updateNodePool: (id: string, payload: Partial<NodePool>) =>
    apiRequest<NodePool>(`/api/v1/node-pools/${id}/`, json('PATCH', payload)),
  nodes: () => apiRequest<Page<ManagedNode>>('/api/v1/nodes/'),
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
  accessProfiles: () => apiRequest<Page<AccessProfile>>('/api/v1/access-profiles/'),
  createAccessProfile: (value: string | Record<string, unknown>, key: string = crypto.randomUUID()) =>
    apiRequest<AccessProfile>('/api/v1/access-profiles/', json('POST', typeof value === 'string' ? { name: value } : value, { 'Idempotency-Key': key })),
  updateAccessProfile: (id: string, payload: Record<string, unknown>, key: string = crypto.randomUUID()) =>
    apiRequest<AccessProfile>(`/api/v1/access-profiles/${id}/`, json('PATCH', payload, { 'Idempotency-Key': key })),
  subscriptionPlans: () => apiRequest<Page<SubscriptionPlan>>('/api/v1/subscriptions/plans/'),
  saveSubscriptionPlan: (payload: Omit<SubscriptionPlan, 'id'>, id?: string) =>
    apiRequest<SubscriptionPlan>(`/api/v1/subscriptions/plans/${id ? `${id}/` : ''}`, json(id ? 'PATCH' : 'POST', payload, { 'Idempotency-Key': crypto.randomUUID() })),
  subscriptionCatalog: () => apiRequest<{ items: ProtocolOption[] }>('/api/v1/subscriptions/catalog/'),
  createSubscriptionProtocol: (payload: Record<string, unknown>) =>
    apiRequest<{id: string}>('/api/v1/subscriptions/catalog/', json('POST', payload, { 'Idempotency-Key': crypto.randomUUID() })),
  subscriptionDetail: (id: string) => apiRequest<SubscriptionDetail>(`/api/v1/subscriptions/${id}/`),
  assignSubscription: (id: string, protocolIds: string[], key: string = crypto.randomUUID()) =>
    apiRequest<{operation_ids: string[]; pending: boolean}>(`/api/v1/subscriptions/${id}/assign/`, json('POST', { protocol_ids: protocolIds }, { 'Idempotency-Key': key })),
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
