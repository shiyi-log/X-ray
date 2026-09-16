import type { components } from './generated/schema';
import { apiRequest } from './request';

export type CloudAccount = components['schemas']['CloudAccount'];
export type NodePool = components['schemas']['NodePool'];
export type ManagedNode = components['schemas']['ManagedNode'];
export type Operation = components['schemas']['Operation'];
export type AccessProfile = components['schemas']['AccessProfile'];
export type Subscription = components['schemas']['Subscription'];
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
  createNodePool: (payload: { name: string; quota: number }) =>
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
  createAccessProfile: (name: string) =>
    apiRequest<AccessProfile>('/api/v1/access-profiles/', json('POST', { name })),
  subscriptions: () => apiRequest<Page<Subscription>>('/api/v1/subscriptions/'),
  auditEvents: () => apiRequest<Page<AuditEvent>>('/api/v1/audit-events/'),
  createPreview: (payload: Record<string, unknown>) =>
    apiRequest<ActionPreview>('/api/v1/operations/previews/', json('POST', payload)),
  issueSubscription: (profileId: string) =>
    apiRequest<SecretDelivery>(
      `/api/v1/access-profiles/${profileId}/subscription/`,
      json('POST', {}),
    ),
  rotateSubscription: (subscriptionId: string) =>
    apiRequest<SecretDelivery>(
      `/api/v1/subscriptions/${subscriptionId}/rotate/`,
      json('POST', {}),
    ),
  publishSubscription: (subscriptionId: string) =>
    apiRequest<Subscription>(
      `/api/v1/subscriptions/${subscriptionId}/publish/`,
      json('POST', {}),
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
