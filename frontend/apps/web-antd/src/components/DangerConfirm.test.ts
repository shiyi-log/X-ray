import { mount } from '@vue/test-utils';

import DangerConfirm from './DangerConfirm.vue';

const preview = {
  id: '11111111-1111-4111-8111-111111111111',
  kind: 'subscription.revoke',
  target_id: '22222222-2222-4222-8222-222222222222',
  required_phrase: '确认强制撤销',
  expires_at: new Date(Date.now() + 300_000).toISOString(),
  snapshot: {
    impacted_profiles: [{ id: '33333333-3333-4333-8333-333333333333', name: '共享设备' }],
  },
};

describe('DangerConfirm', () => {
  it('只有确认文本精确匹配且预览未过期时提交全新幂等键', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => '44444444-4444-4444-8444-444444444444' });
    const wrapper = mount(DangerConfirm, { props: { open: true, preview } });
    const button = wrapper.get('[data-testid="danger-submit"]');
    expect(button.attributes('disabled')).toBeDefined();

    await wrapper.get('[aria-label="确认文本"]').setValue(preview.required_phrase);
    expect(button.attributes('disabled')).toBeUndefined();
    await button.trigger('click');

    expect(wrapper.emitted('confirm')?.[0]).toEqual([
      {
        preview_id: preview.id,
        confirmation: preview.required_phrase,
        idempotency_key: '44444444-4444-4444-8444-444444444444',
      },
    ]);
  });

  it('预览刷新后清除旧确认文本，并明确显示 step-up 要求', async () => {
    const wrapper = mount(DangerConfirm, {
      props: { open: true, preview, errorCode: 'STEP_UP_REQUIRED' },
    });
    await wrapper.get('[aria-label="确认文本"]').setValue(preview.required_phrase);
    await wrapper.setProps({
      preview: { ...preview, id: '55555555-5555-4555-8555-555555555555' },
    });

    expect((wrapper.get('[aria-label="确认文本"]').element as HTMLInputElement).value).toBe('');
    expect(wrapper.text()).toContain('近期身份验证已过期');
  });
});
