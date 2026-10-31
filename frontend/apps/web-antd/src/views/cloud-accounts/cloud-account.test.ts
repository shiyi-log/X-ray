import { DOMWrapper, flushPromises, mount } from '@vue/test-utils';

import { resourcesApi } from '@/api/resources';

import CloudAccounts from './index.vue';

function inputFor(dialog: DOMWrapper<Element>, labelText: string) {
  const label = [...dialog.element.querySelectorAll('label')].find(
    (item) => item.textContent === labelText,
  );
  expect(label, `missing label ${labelText}`).toBeDefined();
  return dialog.get<HTMLInputElement>(`input[id="${label!.htmlFor}"]`);
}

describe('cloud account form with real Ant components', () => {
  it('lets the administrator enable or disable a cloud account from the list', async () => {
    const account = {
      id: 'account-1', name: '测试账号', provider: 'aws_lightsail',
      external_account_id: 'external-1', credential_version: 1,
      enabled: true, validated_at: null, last_validation_code: 'OK',
    } as const;
    vi.spyOn(resourcesApi, 'cloudAccounts').mockResolvedValue({
      items: [account], total: 1, page: 1, page_size: 20,
    });
    const updateAccount = vi.spyOn(resourcesApi, 'updateCloudAccount').mockResolvedValue({
      ...account, enabled: false,
    });
    const wrapper = mount(CloudAccounts, {
      attachTo: document.body,
      global: { stubs: { transition: false, 'transition-group': false } },
    });

    try {
      await flushPromises();
      const toggle = wrapper.get('[role="switch"][aria-label="停用 测试账号"]');
      await toggle.trigger('click');
      await vi.waitFor(() => expect(updateAccount).toHaveBeenCalledWith('account-1', { enabled: false }));
      await flushPromises();
      expect(wrapper.get('[role="switch"][aria-label="启用 测试账号"]').attributes('aria-checked')).toBe('false');
    } finally {
      wrapper.unmount();
    }
  });

  it('keeps the Singapore default, validates credentials and submits an empty region before clearing a failed request', async () => {
    vi.spyOn(resourcesApi, 'cloudAccounts').mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 20,
    });
    const createAccount = vi.spyOn(resourcesApi, 'createCloudAccount')
      .mockRejectedValue(new Error('本地模拟校验失败'));
    const fetch = vi.fn(() => {
      throw new Error('Unexpected network request');
    });
    vi.stubGlobal('fetch', fetch);
    const wrapper = mount(CloudAccounts, {
      attachTo: document.body,
      global: { stubs: { transition: false, 'transition-group': false } },
    });

    try {
      await flushPromises();
      const add = wrapper.findAll('button').find((item) => item.text() === '添加账号')!;
      await add.trigger('click');
      await flushPromises();
      const dialog = new DOMWrapper(document.querySelector('[role="dialog"]')!);
      expect(inputFor(dialog, '区域').element.value).toBe('ap-southeast-1');

      await inputFor(dialog, '名称').setValue('本地表单测试');
      await dialog.get('form').trigger('submit');
      await vi.waitFor(() => {
        expect(dialog.text()).toContain('请输入 Access Key');
        expect(dialog.text()).toContain('请输入 Secret Key');
      });
      expect(createAccount).not.toHaveBeenCalled();

      await inputFor(dialog, '区域').setValue('');
      await inputFor(dialog, 'Access Key').setValue('fixture-access-only');
      await inputFor(dialog, 'Secret Key').setValue('fixture-secret-only');
      await dialog.get('form').trigger('submit');
      await vi.waitFor(() => expect(createAccount).toHaveBeenCalledTimes(1));
      expect(createAccount).toHaveBeenCalledWith({
        name: '本地表单测试',
        provider: 'aws_lightsail',
        region: '',
        credentials: {
          access_key_id: 'fixture-access-only',
          secret_access_key: 'fixture-secret-only',
        },
      });
      await flushPromises();
      expect(inputFor(dialog, 'Access Key').element.value).toBe('');
      expect(inputFor(dialog, 'Secret Key').element.value).toBe('');
      expect(dialog.get('.ant-alert').text()).toContain('本地模拟校验失败');
      expect(document.querySelector('[role="dialog"]')).not.toBeNull();
      expect(fetch).not.toHaveBeenCalled();
    } finally {
      wrapper.unmount();
      vi.unstubAllGlobals();
    }
  });

  it('clears both credentials on cancel and restores the region when reopened', async () => {
    vi.spyOn(resourcesApi, 'cloudAccounts').mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 20,
    });
    const createAccount = vi.spyOn(resourcesApi, 'createCloudAccount');
    const fetch = vi.fn(() => {
      throw new Error('Unexpected network request');
    });
    vi.stubGlobal('fetch', fetch);
    const wrapper = mount(CloudAccounts, {
      attachTo: document.body,
      global: { stubs: { transition: false, 'transition-group': false } },
    });

    try {
      await flushPromises();
      const add = wrapper.findAll('button').find((item) => item.text() === '添加账号')!;
      await add.trigger('click');
      await flushPromises();
      const dialog = new DOMWrapper(document.querySelector('[role="dialog"]')!);
      await inputFor(dialog, 'Access Key').setValue('fixture-access-only');
      await inputFor(dialog, 'Secret Key').setValue('fixture-secret-only');
      await inputFor(dialog, '区域').setValue('');

      await dialog.get('.ant-modal-close').trigger('click');
      await vi.waitFor(() => {
        const modal = document.querySelector('.ant-modal-wrap') as HTMLElement | null;
        expect(modal === null || modal.style.display === 'none').toBe(true);
      });
      await add.trigger('click');
      await flushPromises();
      const reopened = new DOMWrapper(document.querySelector('[role="dialog"]')!);
      expect(inputFor(reopened, 'Access Key').element.value).toBe('');
      expect(inputFor(reopened, 'Secret Key').element.value).toBe('');
      expect(inputFor(reopened, '区域').element.value).toBe('ap-southeast-1');
      expect(createAccount).not.toHaveBeenCalled();
      expect(fetch).not.toHaveBeenCalled();
    } finally {
      wrapper.unmount();
      vi.unstubAllGlobals();
    }
  });
});
