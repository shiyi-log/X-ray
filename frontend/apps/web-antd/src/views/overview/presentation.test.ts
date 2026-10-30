import { formatOverviewTime, overviewEventLabel } from './presentation';

describe('总览展示格式', () => {
  it('把常见操作标识转换为中文名称，并保留未知标识', () => {
    expect(overviewEventLabel('node.access_sync')).toBe('同步节点访问配置');
    expect(overviewEventLabel('custom.event')).toBe('custom.event');
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
