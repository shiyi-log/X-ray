import 'ant-design-vue/dist/reset.css';
import '@xray/ui/tokens.css';
import './styles.css';

import { createPinia } from 'pinia';
import { createApp } from 'vue';

import App from './App.vue';
import { router } from './router';
import { useSessionStore } from './stores/session';

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
app.use(router);
useSessionStore(pinia).installUnauthorizedHandler();
app.mount('#app');
