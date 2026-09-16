<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue';
import { AlertTriangle, RefreshCw, X } from 'lucide-vue-next';

import type { ActionPreview } from '@/api/resources';

interface ConfirmationPayload {
  preview_id: string;
  confirmation: string;
  idempotency_key: string;
}

const props = withDefaults(
  defineProps<{
    open: boolean;
    preview: ActionPreview | null;
    busy?: boolean;
    errorCode?: string;
    errorMessage?: string;
  }>(),
  { busy: false, errorCode: '', errorMessage: '' },
);
const emit = defineEmits<{
  close: [];
  refresh: [];
  confirm: [payload: ConfirmationPayload];
}>();

const typedPhrase = ref('');
const now = ref(Date.now());
const clock = window.setInterval(() => (now.value = Date.now()), 1000);
onScopeDispose(() => window.clearInterval(clock));

watch(
  () => props.preview?.id,
  () => {
    typedPhrase.value = '';
    now.value = Date.now();
  },
);

const expired = computed(
  () => !props.preview || now.value >= Date.parse(props.preview.expires_at),
);
const canSubmit = computed(
  () =>
    Boolean(props.preview) &&
    !expired.value &&
    !props.busy &&
    typedPhrase.value === props.preview?.required_phrase,
);
const impactedProfiles = computed(() => {
  const value = props.preview?.snapshot?.impacted_profiles;
  return Array.isArray(value) ? (value as Array<{ id: string; name: string }>) : [];
});
const expiryText = computed(() => {
  if (!props.preview) return '正在加载预览';
  if (expired.value) return '预览已过期';
  const seconds = Math.max(0, Math.ceil((Date.parse(props.preview.expires_at) - now.value) / 1000));
  return `预览将在 ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')} 后过期`;
});

function submit() {
  if (!canSubmit.value || !props.preview) return;
  emit('confirm', {
    preview_id: props.preview.id,
    confirmation: typedPhrase.value,
    idempotency_key: crypto.randomUUID(),
  });
}
</script>

<template>
  <div v-if="open" class="modal-layer" role="presentation" @mousedown.self="emit('close')">
    <section class="danger-dialog" role="dialog" aria-modal="true" aria-labelledby="danger-title">
      <header>
        <span class="danger-icon"><AlertTriangle :size="20" /></span>
        <div><h2 id="danger-title">强制撤销访问</h2><p>链接会立即失效，节点凭据随后逐节点验证。</p></div>
        <button class="icon-button" type="button" aria-label="关闭" title="关闭" @click="emit('close')"><X :size="18" /></button>
      </header>

      <div v-if="errorCode === 'STEP_UP_REQUIRED'" class="error-band" role="alert">
        近期身份验证已过期。请退出并重新完成密码与 MFA 验证后再次操作。
      </div>
      <div v-else-if="errorMessage" class="error-band" role="alert">{{ errorMessage }}</div>

      <div v-if="preview" class="impact-summary">
        <div><span>目标</span><code>{{ preview.target_id }}</code></div>
        <div><span>有效期</span><strong :class="{ expired }">{{ expiryText }}</strong></div>
      </div>
      <div v-else class="loading-preview">正在生成绑定当前状态的预览...</div>

      <section v-if="impactedProfiles.length" class="impact-list">
        <h3>共享凭据受影响身份</h3>
        <p>共享协议会轮换同节点凭据，以下有效设备需要重新导入新凭据。</p>
        <ul><li v-for="item in impactedProfiles" :key="item.id"><strong>{{ item.name }}</strong><code>{{ item.id }}</code></li></ul>
      </section>

      <label class="confirm-field">
        <span>输入 <strong>{{ preview?.required_phrase }}</strong> 继续</span>
        <input v-model="typedPhrase" aria-label="确认文本" autocomplete="off" :disabled="!preview || expired || busy" />
      </label>

      <footer>
        <button v-if="expired" class="secondary-command" type="button" @click="emit('refresh')"><RefreshCw :size="16" />刷新预览</button>
        <button class="secondary-command" type="button" @click="emit('close')">取消</button>
        <button data-testid="danger-submit" class="danger-command" type="button" :disabled="!canSubmit" @click="submit">
          {{ busy ? '提交中' : '提交操作' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.modal-layer { position: fixed; z-index: 1000; inset: 0; display: grid; place-items: center; padding: 20px; background: rgb(14 24 29 / 54%); }
.danger-dialog { width: min(100%, 620px); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid #e6c1bc; border-radius: 6px; background: white; box-shadow: var(--x-shadow); }
header { display: grid; grid-template-columns: 38px 1fr 36px; gap: 12px; align-items: start; padding: 19px 20px; border-bottom: 1px solid var(--x-border); }
.danger-icon { width: 36px; height: 36px; display: grid; place-items: center; color: white; border-radius: 5px; background: var(--x-danger); }
h2, h3, p { margin: 0; letter-spacing: 0; }
h2 { font-size: 17px; }
header p { margin-top: 4px; color: var(--x-text-muted); font-size: 12px; }
.error-band { margin: 16px 20px 0; padding: 10px 12px; color: var(--x-danger); background: #fff1f0; border-left: 3px solid var(--x-danger); font-size: 12px; }
.impact-summary { display: grid; grid-template-columns: 1fr 1fr; margin: 18px 20px 0; border: 1px solid var(--x-border); }
.impact-summary > div { min-width: 0; display: grid; gap: 5px; padding: 11px 12px; }
.impact-summary > div + div { border-left: 1px solid var(--x-border); }
.impact-summary span { color: var(--x-text-muted); font-size: 11px; }
.impact-summary code { overflow: hidden; font-size: 11px; text-overflow: ellipsis; }
.expired { color: var(--x-danger); }
.loading-preview { margin: 18px 20px 0; padding: 14px; color: var(--x-text-muted); border: 1px solid var(--x-border); }
.impact-list { margin: 14px 20px 0; padding: 13px; background: #fff8e8; border-left: 3px solid var(--x-warning); }
.impact-list h3 { font-size: 13px; }
.impact-list p { margin-top: 4px; color: #74570d; font-size: 12px; }
.impact-list ul { display: grid; gap: 6px; margin: 10px 0 0; padding: 0; list-style: none; }
.impact-list li { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.impact-list code { max-width: 55%; overflow: hidden; color: var(--x-text-muted); text-overflow: ellipsis; }
.confirm-field { display: grid; gap: 7px; margin: 18px 20px; font-size: 12px; }
.confirm-field input { height: 38px; padding: 0 10px; border: 1px solid #cbd5dc; border-radius: 4px; font: 14px/1 var(--x-font); }
footer { display: flex; justify-content: flex-end; gap: 9px; padding: 14px 20px; border-top: 1px solid var(--x-border); }
.danger-command { min-height: 36px; padding: 0 14px; border: 1px solid var(--x-danger); border-radius: 5px; color: white; background: var(--x-danger); font: 600 13px/1 var(--x-font); cursor: pointer; }
.danger-command:disabled { opacity: .5; cursor: not-allowed; }
@media (max-width: 560px) { .modal-layer { padding: 0; align-items: end; } .danger-dialog { max-height: 92vh; border-radius: 6px 6px 0 0; } .impact-summary { grid-template-columns: 1fr; } .impact-summary > div + div { border-left: 0; border-top: 1px solid var(--x-border); } footer { flex-wrap: wrap; } footer button { flex: 1; } }
</style>
