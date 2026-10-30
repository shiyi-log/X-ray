const eventLabels: Record<string, string> = {
  'node.access_sync': '同步节点访问配置',
  'node.firewall_open': '开放节点防火墙规则',
  'node.create': '创建节点',
  'node.reconcile': '协调节点状态',
  'node.quarantine': '隔离节点',
  'node.reinstall': '重装节点',
  'node.rotate_ip': '轮换节点地址',
  'subscription.revoke': '撤销订阅访问',
  'operation.submit.node.access_sync': '提交节点访问配置同步',
  'operation.submit.node.firewall_open': '提交节点防火墙规则变更',
};

const offsetDateTimePattern =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export function overviewEventLabel(value: string): string {
  return eventLabels[value] ?? value;
}

export function formatOverviewTime(value?: string | null): string {
  if (!value || !offsetDateTimePattern.test(value)) return '时间未知';

  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return '时间未知';

  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(timestamp);
  const fields = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]));
  return `${fields.year}-${fields.month}-${fields.day} ${fields.hour}:${fields.minute}`;
}
