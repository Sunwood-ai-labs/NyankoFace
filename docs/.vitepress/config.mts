import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'
import type { Plugin } from 'vite'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repository = 'https://github.com/Sunwood-ai-labs/NyankoFace'
const base = process.env.VITEPRESS_BASE ?? '/NyankoFace/'
const brandVersion = '20260807-paw-v1'
const configDir = dirname(fileURLToPath(import.meta.url))
const sharedBrandAssets = {
  'apple-touch-icon.png': resolve(configDir, '../../frontend/app/apple-icon.png'),
  'pwa-192x192.png': resolve(configDir, '../../frontend/public/brand/pwa-192x192.png'),
  'pwa-512x512.png': resolve(configDir, '../../frontend/public/brand/nyankoface-paw-logo.png'),
  'maskable-512x512.png': resolve(configDir, '../../frontend/public/brand/maskable-512x512.png'),
  'mask-icon.svg': resolve(configDir, '../../frontend/public/brand/mask-icon.svg')
} as const
const docsManifest = JSON.stringify({
  id: '.',
  name: 'NyankoFace Documentation',
  short_name: 'NyankoFace Docs',
  description: 'NyankoFace guides, articles, and knowledge atlas',
  start_url: '.',
  scope: '.',
  display: 'standalone',
  background_color: '#06132e',
  theme_color: '#06132e',
  icons: [
    { src: `./pwa-192x192.png?v=${brandVersion}`, sizes: '192x192', type: 'image/png', purpose: 'any' },
    { src: `./pwa-512x512.png?v=${brandVersion}`, sizes: '512x512', type: 'image/png', purpose: 'any' },
    { src: `./maskable-512x512.png?v=${brandVersion}`, sizes: '512x512', type: 'image/png', purpose: 'maskable' }
  ]
}, null, 2)

function sharedBrandAssetsPlugin(): Plugin {
  const contentType = (name: string) => name.endsWith('.svg')
    ? 'image/svg+xml'
    : name.endsWith('.webmanifest')
      ? 'application/manifest+json'
      : 'image/png'
  const source = async (name: string) => name === 'manifest.webmanifest'
    ? docsManifest
    : readFile(sharedBrandAssets[name as keyof typeof sharedBrandAssets])
  const names = [...Object.keys(sharedBrandAssets), 'manifest.webmanifest']
  return {
    name: 'nyankoface-shared-brand-assets',
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const pathname = new URL(request.url || '/', 'http://localhost').pathname
        const name = names.find((candidate) => pathname.endsWith(`/${candidate}`))
        if (!name) return next()
        response.statusCode = 200
        response.setHeader('Content-Type', contentType(name))
        response.end(await source(name))
      })
    },
    async generateBundle() {
      for (const name of names) {
        this.emitFile({ type: 'asset', fileName: name, source: await source(name) })
      }
    }
  }
}

export default withMermaid(defineConfig({
  title: 'NyankoFace',
  description: 'A local-first, Forgejo-backed AI community hub for models, datasets, Docker Spaces, Skills, MCPs, and versioned Prompts.',
  lang: 'en-US',
  base,
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', sizes: 'any', href: `${base}nyankoface.svg?v=${brandVersion}` }],
    ['link', { rel: 'icon', type: 'image/png', sizes: '192x192', href: `${base}pwa-192x192.png?v=${brandVersion}` }],
    ['link', { rel: 'shortcut icon', href: `${base}nyankoface.svg?v=${brandVersion}` }],
    ['link', { rel: 'apple-touch-icon', sizes: '180x180', href: `${base}apple-touch-icon.png?v=${brandVersion}` }],
    ['link', { rel: 'mask-icon', href: `${base}mask-icon.svg?v=${brandVersion}`, color: '#f59e0b' }],
    ['link', { rel: 'manifest', href: `${base}manifest.webmanifest?v=${brandVersion}` }],
    ['meta', { id: 'nyankoface-theme-color', name: 'theme-color', content: '#ffffff' }],
    ['meta', { property: 'og:image', content: `${base}social-card.svg?v=${brandVersion}` }],
    ['script', {}, `(() => { const sync = () => document.querySelector('#nyankoface-theme-color')?.setAttribute('content', document.documentElement.classList.contains('dark') ? '#06132e' : '#ffffff'); sync(); new MutationObserver(sync).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] }); })();`]
  ],
  vite: { plugins: [sharedBrandAssetsPlugin()] },
  locales: {
    root: {
      label: 'English',
      lang: 'en-US',
      title: 'NyankoFace',
      description: 'Build and run a local AI community hub on your own Docker host.',
      themeConfig: {
        nav: enNav(),
        sidebar: enSidebar(),
        outline: { label: 'On this page' },
        docFooter: { prev: 'Previous', next: 'Next' },
        editLink: { pattern: `${repository}/edit/main/docs/:path`, text: 'Edit this page on GitHub' }
      }
    },
    ja: {
      label: '日本語',
      lang: 'ja-JP',
      link: '/ja/',
      title: 'NyankoFace',
      description: '自分のDockerホストで動かす、ローカルファーストのAIコミュニティハブ。',
      themeConfig: {
        nav: jaNav(),
        sidebar: jaSidebar(),
        outline: { label: 'このページの内容' },
        docFooter: { prev: '前へ', next: '次へ' },
        editLink: { pattern: `${repository}/edit/main/docs/:path`, text: 'GitHubでこのページを編集' }
      }
    }
  },
  themeConfig: {
    logo: '/pwa-512x512.png',
    siteTitle: 'NyankoFace',
    search: { provider: 'local' },
    socialLinks: [{ icon: 'github', link: repository }],
    footer: {
      message: 'Released under the MIT License. Third-party components retain their own licenses.',
      copyright: 'Copyright © 2026 Sunwood AI Labs'
    }
  },
  mermaid: {
    theme: 'base',
    themeVariables: {
      primaryColor: '#f4f1e8',
      primaryTextColor: '#18211d',
      primaryBorderColor: '#d95d39',
      lineColor: '#496459',
      secondaryColor: '#e8e1d2',
      tertiaryColor: '#ffffff',
      fontFamily: '"Avenir Next", Avenir, "Noto Sans JP", sans-serif'
    },
    flowchart: {
      curve: 'basis',
      htmlLabels: true
    }
  },
  mermaidPlugin: {
    class: 'nyankoface-mermaid'
  },
  sitemap: { hostname: 'https://sunwood-ai-labs.github.io/NyankoFace/' }
}))

function enNav() {
  return [
    { text: 'Field notes', link: '/articles/' },
    { text: 'Knowledge atlas', link: '/wiki/' },
    {
      text: 'Build',
      items: [
        { text: 'Getting started', link: '/guide/getting-started' },
        { text: 'Release v0.6.0', link: '/guide/releases/v0.6.0' },
        { text: 'Release v0.5.0', link: '/guide/releases/v0.5.0' },
        { text: 'Release v0.4.0', link: '/guide/releases/v0.4.0' },
        { text: 'Release v0.3.0', link: '/guide/releases/v0.3.0' },
        { text: 'Docker Spaces', link: '/guide/spaces' },
        { text: 'NyankoFace Pages', link: '/guide/pages' },
        { text: 'Repository pipelines', link: '/guide/pipelines' }
      ]
    },
    {
      text: 'Operate',
      items: [
        { text: 'Automated maintenance', link: '/guide/automated-maintenance' },
        { text: 'Visual QA', link: '/guide/visual-qa' },
        { text: 'Operations', link: '/guide/operations' },
        { text: 'Upgrade and data retention', link: '/guide/upgrading' },
        { text: 'Troubleshooting', link: '/guide/troubleshooting' }
      ]
    }
  ]
}

function jaNav() {
  return [
    { text: '読みもの', link: '/ja/articles/' },
    { text: '知識地図', link: '/ja/wiki/' },
    {
      text: 'つくる',
      items: [
        { text: 'はじめに', link: '/ja/guide/getting-started' },
        { text: 'Release v0.6.0', link: '/ja/guide/releases/v0.6.0' },
        { text: 'Release v0.5.0', link: '/ja/guide/releases/v0.5.0' },
        { text: 'Release v0.4.0', link: '/ja/guide/releases/v0.4.0' },
        { text: 'Release v0.3.0', link: '/ja/guide/releases/v0.3.0' },
        { text: 'Docker Spaces', link: '/ja/guide/spaces' },
        { text: 'NyankoFace Pages', link: '/ja/guide/pages' },
        { text: 'Repository Pipelines', link: '/ja/guide/pipelines' }
      ]
    },
    {
      text: '運用する',
      items: [
        { text: '自動メンテナンス', link: '/ja/guide/automated-maintenance' },
        { text: 'Visual QA', link: '/ja/guide/visual-qa' },
        { text: '運用', link: '/ja/guide/operations' },
        { text: 'Upgradeとデータ保持', link: '/ja/guide/upgrading' },
        { text: 'トラブルシューティング', link: '/ja/guide/troubleshooting' }
      ]
    }
  ]
}

function enSidebar() {
  return {
    '/articles/': [{
      text: 'Field notes',
      items: [
        { text: 'All field notes', link: '/articles/' },
        { text: 'NyankoFace v0.6.0', link: '/articles/nyankoface-v0-6-0' },
        { text: 'NyankoFace v0.5.0', link: '/articles/nyankoface-v0-5-0' },
        { text: 'NyankoFace v0.4.0', link: '/articles/nyankoface-v0-4-0' },
        { text: 'NyankoFace v0.3.0', link: '/articles/nyankoface-v0-3-0' },
        { text: 'NyankoFace v0.2.0', link: '/articles/nyankoface-v0-2-0' },
        { text: 'NyankoFace v0.1.0', link: '/articles/nyankoface-v0-1-0' },
        { text: 'Why a local AI hub?', link: '/articles/local-first-hub' },
        { text: 'Independent review before merge', link: '/articles/independent-review' },
        { text: 'A Space is app + repository', link: '/articles/docker-spaces' }
      ]
    }],
    '/wiki/': wikiSidebar(''),
    '/guide/': guideSidebar('')
  }
}

function jaSidebar() {
  return {
    '/ja/articles/': [{
      text: '読みもの',
      items: [
        { text: 'すべての読みもの', link: '/ja/articles/' },
        { text: 'NyankoFace v0.6.0', link: '/ja/articles/nyankoface-v0-6-0' },
        { text: 'NyankoFace v0.5.0', link: '/ja/articles/nyankoface-v0-5-0' },
        { text: 'NyankoFace v0.4.0', link: '/ja/articles/nyankoface-v0-4-0' },
        { text: 'NyankoFace v0.3.0', link: '/ja/articles/nyankoface-v0-3-0' },
        { text: 'NyankoFace v0.2.0', link: '/ja/articles/nyankoface-v0-2-0' },
        { text: 'NyankoFace v0.1.0', link: '/ja/articles/nyankoface-v0-1-0' },
        { text: 'ローカルAIハブという選択', link: '/ja/articles/local-first-hub' },
        { text: '自動マージの前に、別の目を置く', link: '/ja/articles/independent-review' },
        { text: 'Spaceはアプリで、リポジトリでもある', link: '/ja/articles/docker-spaces' }
      ]
    }],
    '/ja/wiki/': wikiSidebar('/ja', true),
    '/ja/guide/': guideSidebar('/ja', true)
  }
}

function wikiSidebar(prefix: string, ja = false) {
  return [{
    text: ja ? 'Knowledge Atlas' : 'Knowledge atlas',
    items: [
      { text: ja ? '知識地図' : 'Atlas index', link: `${prefix}/wiki/` },
      { text: ja ? 'プラットフォーム地図' : 'Platform map', link: `${prefix}/wiki/platform-map` },
      { text: ja ? 'カタログの構造' : 'Catalog anatomy', link: `${prefix}/wiki/catalog` },
      { text: ja ? '実行環境' : 'Runtime', link: `${prefix}/wiki/runtime` },
      { text: ja ? 'エージェント運用' : 'Agent operations', link: `${prefix}/wiki/agent-operations` },
      { text: ja ? '用語集' : 'Glossary', link: `${prefix}/wiki/glossary` }
    ]
  }]
}

function guideSidebar(prefix: string, ja = false) {
  return [{
    text: ja ? '実践ガイド' : 'Practical guides',
    items: [
      { text: ja ? 'はじめに' : 'Getting started', link: `${prefix}/guide/getting-started` },
      { text: 'Release v0.6.0', link: `${prefix}/guide/releases/v0.6.0` },
      { text: 'Release v0.5.0', link: `${prefix}/guide/releases/v0.5.0` },
      { text: 'Release v0.4.0', link: `${prefix}/guide/releases/v0.4.0` },
      { text: 'Release v0.3.0', link: `${prefix}/guide/releases/v0.3.0` },
      { text: 'Release v0.2.0', link: `${prefix}/guide/releases/v0.2.0` },
      { text: 'Release v0.1.0', link: `${prefix}/guide/releases/v0.1.0` },
      { text: ja ? 'アーキテクチャ' : 'Architecture', link: `${prefix}/guide/architecture` },
      { text: ja ? 'GPU worker' : 'GPU workers', link: `${prefix}/guide/gpu-workers` },
      { text: ja ? '統一APIと認証' : 'Unified API and authentication', link: `${prefix}/guide/unified-api` },
      { text: ja ? 'seedアプリとカタログ' : 'Seed applications and catalogs', link: `${prefix}/guide/seed-apps` },
      { text: ja ? 'カタログのメトリクス並び替え' : 'Catalog metric sorting', link: `${prefix}/guide/catalog-metric-sorting` },
      { text: ja ? '実測メトリクスと時系列' : 'Measured metrics and time series', link: `${prefix}/guide/metrics-time-series` },
      { text: 'Docker Spaces', link: `${prefix}/guide/spaces` },
      { text: ja ? 'SpaceのVariables／Secrets' : 'Space Variables and Secrets', link: `${prefix}/guide/space-environment` },
      { text: 'NyankoFace Pages', link: `${prefix}/guide/pages` },
      { text: ja ? 'Repository Pipelines' : 'Repository pipelines', link: `${prefix}/guide/pipelines` },
      { text: 'NyankoFace MCP Server', link: `${prefix}/guide/mcp-server` },
      { text: ja ? 'MCP実クライアントQA' : 'Live MCP client QA', link: `${prefix}/guide/mcp-live-clients` },
      { text: ja ? 'MCP管理Runbook' : 'MCP administration runbook', link: `${prefix}/guide/mcp-administration` },
      { text: ja ? 'ページ遷移のパフォーマンス' : 'Navigation performance', link: `${prefix}/guide/performance` },
      { text: 'Visual QA', link: `${prefix}/guide/visual-qa` },
      { text: ja ? '自動メンテナンス' : 'Automated maintenance', link: `${prefix}/guide/automated-maintenance` },
      { text: ja ? '運用' : 'Operations', link: `${prefix}/guide/operations` },
      { text: ja ? 'Upgradeとデータ保持' : 'Upgrade and data retention', link: `${prefix}/guide/upgrading` },
      { text: ja ? 'トラブルシューティング' : 'Troubleshooting', link: `${prefix}/guide/troubleshooting` }
    ]
  }]
}
