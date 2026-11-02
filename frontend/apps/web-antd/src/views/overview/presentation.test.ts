import {
  auditActionLabel,
  formatOverviewTime,
  operationLabel,
  operationStepLabel,
  operationStepPhaseLabel,
  overviewEventLabel,
  targetTypeLabel,
} from './presentation';

describe('总览展示格式', () => {
  it('把常见操作标识转换为中文名称，并保留未知标识', () => {
    expect(overviewEventLabel('node.access_sync')).toBe('同步节点访问配置');
    expect(overviewEventLabel('custom.event')).toBe('custom.event');
    expect(operationLabel('node.delete')).toBe('删除节点');
    expect(operationLabel('operation.submit.node.delete')).toBe('提交删除节点');
    expect(auditActionLabel('operation.submit.node.delete')).toBe('提交删除节点');
    expect(auditActionLabel('subscription.management.mutate')).toBe('修改订阅管理');
    expect(targetTypeLabel('node')).toBe('服务器');
    expect(operationStepLabel('cloud.refresh')).toBe('读取云端状态');
    expect(operationStepLabel('cloud.delete.read_after_write')).toBe('核对删除结果');
    expect(operationStepLabel('security.apply_config')).toBe('应用安全配置');
    expect(operationStepPhaseLabel('security')).toBe('安全');
  });

  it('将带时区的事件时间统一显示为上海时间', () => {
    expect(formatOverviewTime('2026-10-29T05:00:00Z')).toBe('2026-10-29 13:00');
    expect(formatOverviewTime('2026-10-29T13:00:00+08:00')).toBe('2026-10-29 13:00');
  });

  it.each([undefined, '2026-10-29T05:00:00', 'not-a-time'])(
    '对缺失、无时区或非法时间显示未知：%s',
    (value) => {
      expect(formatOverviewTime(value)).toBe('时间未知');
    },
  );
});
