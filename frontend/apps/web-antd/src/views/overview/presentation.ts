const eventLabels: Record<string, string> = {
  'node.access_sync': '同步节点访问配置',
  'node.firewall_open': '开放节点防火墙规则',
  'node.create': '创建节点',
  'node.delete': '删除节点',
  'node.refresh': '更新云端状态',
  'node.start': '启动节点',
  'node.stop': '停止节点',
  'node.reboot': '重启节点',
  'node.reconcile': '协调节点状态',
  'node.quarantine': '隔离节点',
  'node.reinstall': '重装节点',
  'node.rotate_ip': '轮换节点地址',
  'subscription.revoke': '撤销订阅访问',
  'subscription.management.mutate': '修改订阅管理',
  'subscription.token_revoke': '撤销订阅令牌',
  'system.provider_identity_network.update': '更新云身份校验联网设置',
  'system.node_status_sync.update': '更新服务器状态同步设置',
  'operation.submit.node.access_sync': '提交节点访问配置同步',
  'operation.submit.node.firewall_open': '提交节点防火墙规则变更',
};

const targetLabels: Record<string, string> = {
  node: '服务器',
  cloud_account: '云账号',
  CloudAccount: '云账号',
  access_profile: '访问配置',
  subscription: '订阅',
  system: '系统',
  system_setting: '系统设置',
};

const stepLabels: Record<string, string> = {
  'cloud.refresh': '读取云端状态',
  'cloud.create': '创建云服务器',
  'cloud.reconcile': '核对云端状态',
  'cloud.start': '启动云服务器',
  'cloud.stop': '停止云服务器',
  'cloud.reboot': '重启云服务器',
  'cloud.delete.preflight': '删除前检查',
  'cloud.delete': '删除云服务器',
  'cloud.start.read_after_write': '核对启动结果',
  'cloud.stop.read_after_write': '核对停止结果',
  'cloud.reboot.read_after_write': '核对重启结果',
  'cloud.delete.read_after_write': '核对删除结果',
  'cloud.read': '读取云端信息',
  'cloud.readback': '核对云端结果',
  'security.capture_sessions': '记录待撤销会话',
  'security.apply_config': '应用安全配置',
  'security.verify_revocation': '验证访问撤销结果',
  'security.quarantine': '隔离服务器',
};

const stepPhaseLabels: Record<string, string> = {
  cloud: '云端',
  security: '安全',
};

const offsetDateTimePattern =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export function overviewEventLabel(value: string): string {
  return eventLabels[value] ?? value;
}

export function operationLabel(value: string): string {
  const direct = eventLabels[value];
  if (direct) return direct;
  for (const prefix of ['operation.submit.', 'operation.retry.']) {
    if (value.startsWith(prefix)) {
      const action = value.slice(prefix.length);
      const verb = prefix === 'operation.submit.' ? '提交' : '重试';
      return `${verb}${eventLabels[action] ?? action}`;
    }
  }
  return value;
}

export function auditActionLabel(value: string): string {
  const direct = operationLabel(value);
  if (direct !== value) return direct;
  return value;
}

export function targetTypeLabel(value: string): string {
  return targetLabels[value] ?? value;
}

export function operationStepLabel(value?: string | null): string {
  if (!value) return '-';
  return stepLabels[value] ?? value;
}

export function operationStepPhaseLabel(value?: string | null): string {
  if (!value) return '-';
  return stepPhaseLabels[value] ?? value;
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
