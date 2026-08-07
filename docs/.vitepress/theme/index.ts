import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import AtlasHome from './components/AtlasHome.vue'
import Layout from './Layout.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ app }) {
    app.component('AtlasHome', AtlasHome)
  }
} satisfies Theme
