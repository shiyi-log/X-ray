<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue';
import { Check, Clipboard, KeyRound, X } from 'lucide-vue-next';

import type { SecretDelivery as SecretDeliveryValue } from '@/api/resources';
import { registerSensitiveClearer } from '@/api/request';

const props = defineProps<{ open: boolean; delivery: SecretDeliveryValue | null }>();
const emit = defineEmits<{ close: [] }>();
const secret = ref<SecretDeliveryValue | null>(null);
const copied = ref('');
let timer: number | undefined;

function wipe() {
  secret.value = null;
  copied.value = '';
  if (timer) window.clearTimeout(timer);
  timer = undefined;
}

function close() {
  wipe();
  emit('close');
}

watch(
  () => [props.open, props.delivery] as const,
  ([open, value]) => {
    wipe();
    if (!open || !value) return;
    secret.value = { ...value, urls: { ...value.urls } };
    timer = window.setTimeout(close, 5 * 60 * 1000);
  },
  { immediate: true },
);

const unregister = registerSensitiveClearer(() => {
  if (secret.value || props.open) close();
});
onScopeDispose(() => {
  unregister();
  wipe();
});

const formats = computed(() => Object.entries(secret.value?.urls || {}));

async function copy(label: string, value: string) {
  await navigator.clipboard.writeText(value);
  copied.value = label;
  window.setTimeout(() => {
    if (copied.value === label) copied.value = '';
  }, 1600);
}
</script>

<template>
  <div v-if="open && secret" class="modal-layer" role="presentation">
    <section class="secret-dialog" role="dialog" aria-modal="true" aria-labelledby="secret-title">
      <header><span class="secret-icon"><KeyRound :size="20" /></span><div><h2 id="secret-title">一次性交付</h2><p>关闭或五分钟后清除，之后只能显式轮换。</p></div><button class="icon-button" type="button" aria-label="关闭" title="关闭" @click="close"><X :size="18" /></button></header>
      <div class="warning-band">Token 与订阅 URL 不会写入浏览器存储，也无法从服务器再次读取。</div>
      <section class="secret-value"><span>Token</span><code>{{ secret.token }}</code><button data-testid="copy-token" class="copy-button" type="button" @click="copy('token', secret.token)"><Check v-if="copied === 'token'" :size="16" /><Clipboard v-else :size="16" />{{ copied === 'token' ? '已复制' : '复制' }}</button></section>
      <section class="format-list"><div v-for="[name, value] in formats" :key="name"><span>{{ name }}</span><code>{{ value }}</code><button class="icon-button" type="button" :aria-label="`复制 ${name} URL`" :title="`复制 ${name} URL`" @click="copy(name, value)"><Check v-if="copied === name" :size="16" /><Clipboard v-else :size="16" /></button></div></section>
      <footer><button class="command" type="button" @click="close">我已安全保存并关闭</button></footer>
    </section>
  </div>
</template>

<style scoped>
.modal-layer { position: fixed; z-index: 1000; inset: 0; display: grid; place-items: center; padding: 20px; background: rgb(14 24 29 / 54%); }
.secret-dialog { width: min(100%, 720px); max-height: calc(100vh - 40px); overflow: auto; border: 1px solid var(--x-border); border-radius: 6px; background: white; box-shadow: var(--x-shadow); }
header { display: grid; grid-template-columns: 38px 1fr 36px; gap: 12px; align-items: start; padding: 19px 20px; border-bottom: 1px solid var(--x-border); }
.secret-icon { width: 36px; height: 36px; display: grid; place-items: center; color: white; border-radius: 5px; background: var(--x-accent); }
h2, p { margin: 0; letter-spacing: 0; }
h2 { font-size: 17px; } header p { margin-top: 4px; color: var(--x-text-muted); font-size: 12px; }
.warning-band { margin: 16px 20px 0; padding: 10px 12px; color: #74570d; background: #fff8e8; border-left: 3px solid var(--x-warning); font-size: 12px; }
.secret-value { display: grid; grid-template-columns: 1fr auto; gap: 7px 10px; margin: 16px 20px; padding: 13px; border: 1px solid var(--x-border); background: #f7f9fa; }
.secret-value span { grid-column: 1 / -1; color: var(--x-text-muted); font-size: 11px; }
.secret-value code { min-width: 0; overflow-wrap: anywhere; font-size: 12px; }
.copy-button { display: inline-flex; align-items: center; gap: 6px; padding: 0 9px; border: 1px solid var(--x-border); border-radius: 4px; color: var(--x-text); background: white; cursor: pointer; }
.format-list { margin: 0 20px; border: 1px solid var(--x-border); }
.format-list > div { min-height: 58px; display: grid; grid-template-columns: 86px minmax(0, 1fr) 36px; align-items: center; gap: 10px; padding: 8px 10px; border-bottom: 1px solid var(--x-border); }
.format-list > div:last-child { border-bottom: 0; }
.format-list span { text-transform: capitalize; font-size: 12px; font-weight: 650; }
.format-list code { overflow: hidden; color: var(--x-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
footer { display: flex; justify-content: flex-end; padding: 16px 20px; }
@media (max-width: 600px) { .modal-layer { padding: 0; align-items: end; } .secret-dialog { max-height: 92vh; border-radius: 6px 6px 0 0; } .format-list > div { grid-template-columns: 1fr 36px; } .format-list span { grid-column: 1 / -1; } }
</style>
