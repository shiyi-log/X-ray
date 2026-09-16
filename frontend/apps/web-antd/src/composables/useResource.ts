import { onMounted, ref } from 'vue';

export function useResource<T>(loader: () => Promise<T>) {
  const data = ref<T | null>(null);
  const loading = ref(true);
  const error = ref('');

  async function reload() {
    loading.value = true;
    error.value = '';
    try {
      data.value = await loader();
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '数据加载失败';
    } finally {
      loading.value = false;
    }
  }

  onMounted(() => void reload());
  return { data, loading, error, reload };
}
