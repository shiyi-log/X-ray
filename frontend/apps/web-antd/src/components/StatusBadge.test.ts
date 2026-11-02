import { mount } from '@vue/test-utils';

import StatusBadge from './StatusBadge.vue';

describe('StatusBadge', () => {
  it.each([
    ['PENDING', '待处理'],
    ['ACCEPTED', '已受理'],
    ['starting', '启动中'],
    ['stopping', '停止中'],
    ['rebooting', '重启中'],
    ['shutting-down', '关机中'],
    ['terminating', '终止中'],
    ['PROVISIONED', '已配置'],
    ['DELETED', '已删除'],
    ['OPEN', '开放'],
    ['NORMAL', '正常'],
    ['TRUE', '是'],
    [false, '否'],
    [null, '未知'],
  ])('translates %s to %s', (value, expected) => {
    const wrapper = mount(StatusBadge, { props: { value } });
    expect(wrapper.text()).toBe(expected);
  });

  it('keeps an unknown status visible for diagnosis', () => {
    const wrapper = mount(StatusBadge, { props: { value: 'CUSTOM_STATE' } });
    expect(wrapper.text()).toBe('CUSTOM_STATE');
  });
});
