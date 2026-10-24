import { setupVbenForm } from '@vben/common-ui';

/** Ant Design Vue adapter from the official web-antd template. */
export function initSetupVbenForm() {
  setupVbenForm({
    config: {
      baseModelPropName: 'value',
      modelPropNameMap: { Checkbox: 'checked', Switch: 'checked' },
    },
    defineRules: {
      required: (value, _params, context) =>
        value === undefined || value === null || value === ''
          ? `请输入${context.label}`
          : true,
      selectRequired: (value, _params, context) =>
        value === undefined || value === null
          ? `请选择${context.label}`
          : true,
    },
  });
}
