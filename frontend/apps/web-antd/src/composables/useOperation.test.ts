import { effectScope, nextTick } from 'vue';

import { useOperation } from './useOperation';

const operationId = '11111111-1111-4111-8111-111111111111';

describe('useOperation', () => {
  it('按固定 ID 从服务器恢复并在终态停止轮询', async () => {
    vi.useFakeTimers();
    const responses = [
      { id: operationId, status: 'RUNNING', current_step: 'cloud.create', steps: [] },
      { id: operationId, status: 'SUCCEEDED', current_step: 'done', steps: [] },
    ];
    const fetcher = vi.fn(async () => responses.shift()!);
    const scope = effectScope();
    const state = scope.run(() => useOperation(operationId, { fetcher, pollInterval: 25 }))!;

    await vi.runAllTicks();
    await nextTick();
    expect(state.data.value?.id).toBe(operationId);
    expect(state.data.value?.status).toBe('RUNNING');

    await vi.advanceTimersByTimeAsync(25);
    expect(state.data.value?.status).toBe('SUCCEEDED');
    await vi.advanceTimersByTimeAsync(100);
    expect(fetcher).toHaveBeenCalledTimes(2);

    scope.stop();
    vi.useRealTimers();
  });

  it('API 失败保留错误且不伪造进度', async () => {
    const fetcher = vi.fn(async () => {
      throw new Error('连接失败');
    });
    const scope = effectScope();
    const state = scope.run(() => useOperation(operationId, { fetcher, pollInterval: 1000 }))!;
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(state.data.value).toBeNull();
    expect(state.error.value).toBe('连接失败');
    scope.stop();
  });
});
