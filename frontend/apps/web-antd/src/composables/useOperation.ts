import { onScopeDispose, readonly, ref } from 'vue';

import { apiRequest } from '@/api/request';

export interface OperationStep {
  name: string;
  phase: string;
  status: string;
  attempt: number;
}

export interface OperationDetail {
  id: string;
  kind?: string;
  target_type?: string;
  target_id?: string;
  status: string;
  current_step: string;
  can_cancel?: boolean;
  error_code?: string;
  steps: OperationStep[];
  revocation_nodes?: Array<Record<string, unknown>>;
}

interface Options {
  fetcher?: (id: string) => Promise<OperationDetail>;
  pollInterval?: number;
}

const terminalStates = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED', 'PARTIALLY_SUCCEEDED']);

export function useOperation(operationId: string, options: Options = {}) {
  const data = ref<OperationDetail | null>(null);
  const error = ref('');
  const loading = ref(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  const fetcher =
    options.fetcher ||
    ((id: string) => apiRequest<OperationDetail>(`/api/v1/operations/${id}/`));
  const pollInterval = options.pollInterval ?? 1500;

  function schedule() {
    if (stopped || (data.value && terminalStates.has(data.value.status))) return;
    timer = setTimeout(() => void reload(), pollInterval);
  }

  async function reload() {
    if (stopped || loading.value) return;
    loading.value = true;
    error.value = '';
    try {
      data.value = await fetcher(operationId);
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '操作状态加载失败';
    } finally {
      loading.value = false;
      schedule();
    }
  }

  function stopPolling() {
    stopped = true;
    if (timer) clearTimeout(timer);
  }

  onScopeDispose(stopPolling);
  void reload();

  return {
    data: readonly(data),
    error: readonly(error),
    loading: readonly(loading),
    reload,
    stopPolling,
  };
}
