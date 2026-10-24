import { createApp, defineComponent, h, nextTick, ref, resolveComponent } from 'vue';

import { flushPromises } from '@vue/test-utils';

import { initComponentAdapter } from './components';

describe('component adapter', () => {
  it('registers the Ant modal used by business pages and supports open and cancel', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    const app = createApp(defineComponent({
      setup() {
        const open = ref(false);
        return () => h('section', [
          h('button', { onClick: () => { open.value = true; } }, '添加账号'),
          h(resolveComponent('a-modal'), {
            open: open.value,
            title: '添加云账号',
            footer: null,
            destroyOnClose: true,
            transitionName: '',
            maskTransitionName: '',
            'onUpdate:open': (value: boolean) => { open.value = value; },
          }, { default: () => h('p', '账号表单') }),
        ]);
      },
    }));
    initComponentAdapter(app);

    try {
      app.mount(target);
      await nextTick();
      expect(document.querySelector('[role="dialog"]')).toBeNull();

      target.querySelector('button')!.click();
      await nextTick();
      await flushPromises();
      const dialog = document.querySelector('[role="dialog"]');
      expect(dialog).not.toBeNull();
      expect(dialog?.textContent).toContain('添加云账号');
      expect(dialog?.textContent).toContain('账号表单');

      (dialog!.querySelector('.ant-modal-close') as HTMLButtonElement).click();
      await nextTick();
      await flushPromises();
      expect(document.querySelector('[role="dialog"]')).toBeNull();
    } finally {
      app.unmount();
      target.remove();
    }
  });
});
