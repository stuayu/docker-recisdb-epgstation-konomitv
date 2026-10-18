import { createApp } from 'vue'
import '@fontsource-variable/archivo/wdth.css'
import '@fontsource/ibm-plex-sans-jp/400.css'
import '@fontsource/ibm-plex-sans-jp/500.css'
import '@fontsource/ibm-plex-sans-jp/700.css'
import '@fontsource-variable/jetbrains-mono'
import './style.scss'
import App from './App.vue'

try {
  const theme = localStorage.getItem('edcb-dashboard-theme')
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme
} catch { /* Storage can be disabled in private or restricted browsers. */ }
createApp(App).mount('#app')
