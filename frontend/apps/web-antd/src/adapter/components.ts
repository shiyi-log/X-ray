import { defineComponent, h, type App } from 'vue';

import { globalShareState, setDefaultModalProps } from '@vben/common-ui';

import { Button, Checkbox, Input, InputNumber, Modal, Select, Switch } from 'ant-design-vue';

export function initComponentAdapter(app: App) {
  app.use(Modal);
  setDefaultModalProps({ fullscreenButton: false });

  const createButton = (type: 'default' | 'primary') =>
    defineComponent({
      inheritAttrs: false,
      setup(_props, { attrs, slots }) {
        return () => h(Button, { ...attrs, type }, slots);
      },
    });

  globalShareState.setComponents({
    Checkbox,
    DefaultButton: createButton('default'),
    Input,
    InputNumber,
    InputPassword: Input.Password,
    PrimaryButton: createButton('primary'),
    Select,
    Switch,
    Textarea: Input.TextArea,
  });
}
