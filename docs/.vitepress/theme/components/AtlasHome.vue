<script setup lang="ts">
import { computed } from 'vue'
import { withBase } from 'vitepress'

const props = defineProps<{ locale?: 'en' | 'ja' }>()
const ja = computed(() => props.locale === 'ja')

const copy = computed(() => ja.value ? {
  eyebrow: 'NYANKOFACE FIELD MANUAL · 2026',
  title: '読むほどつながる。\n引くほど深まる。',
  lead: 'NyankoFaceの設計思想を読みものとして理解し、必要な知識をWikiとしてすぐ引ける、運用者と開発者のためのフィールドマニュアル。',
  start: '最初の15分',
  explore: '知識地図を開く',
  sectionRead: '編集部の読みもの',
  sectionReadNote: '背景、判断、検証の物語からNyankoFaceを理解する。',
  sectionWiki: 'Knowledge Atlas',
  sectionWikiNote: '目的や概念から、必要なページへ最短でたどる。',
  sectionPath: '目的から読む',
  latest: 'LATEST FIELD NOTES',
  articles: [
    { title: 'ローカルAIハブという選択', note: 'クラウドの模倣ではなく、手元のGitとDockerをコミュニティへ変える設計。', meta: '思想 · 7分', link: '/ja/articles/local-first-hub' },
    { title: '自動マージの前に、別の目を置く', note: '専門エージェント、司令塔、独立レビュアーをつないだ厳格な保守フロー。', meta: '運用 · 9分', link: '/ja/articles/independent-review' },
    { title: 'Spaceはアプリで、リポジトリでもある', note: 'Dockerfile-firstがGradioからNext.jsまでを一つの体験にする理由。', meta: '実装 · 6分', link: '/ja/articles/docker-spaces' }
  ],
  nodes: [
    { id: '01', title: 'Platform map', note: 'サービス、経路、データ境界', link: '/ja/wiki/platform-map' },
    { id: '02', title: 'Catalog anatomy', note: 'Models / Datasets / Skills / MCPs', link: '/ja/wiki/catalog' },
    { id: '03', title: 'Runtime', note: 'Spaces / Pages / Actions', link: '/ja/wiki/runtime' },
    { id: '04', title: 'Agent operations', note: '委任、レビュー、自動マージ', link: '/ja/wiki/agent-operations' },
    { id: '05', title: 'Glossary', note: '用語と設定値を横断検索', link: '/ja/wiki/glossary' }
  ],
  paths: [
    { label: 'はじめて動かす', detail: 'Compose起動から確認まで', link: '/ja/guide/getting-started' },
    { label: 'Spaceを公開する', detail: 'CPU Dockerアプリの公開', link: '/ja/guide/spaces' },
    { label: '運用を設計する', detail: '権限、TLS、バックアップ', link: '/ja/guide/operations' },
    { label: '見た目を検証する', detail: '全テーマのVisual QA', link: '/ja/guide/visual-qa' }
  ]
} : {
  eyebrow: 'NYANKOFACE FIELD MANUAL · 2026',
  title: 'Read the story.\nTraverse the system.',
  lead: 'An editorial field manual and navigable wiki for understanding, building, and operating the NyankoFace local AI community hub.',
  start: 'The first 15 minutes',
  explore: 'Open the knowledge atlas',
  sectionRead: 'Field notes',
  sectionReadNote: 'Understand NyankoFace through the context, decisions, and evidence behind it.',
  sectionWiki: 'Knowledge atlas',
  sectionWikiNote: 'Enter through a concept and reach the exact reference you need.',
  sectionPath: 'Read by intent',
  latest: 'LATEST FIELD NOTES',
  articles: [
    { title: 'Why a local AI hub?', note: 'Turning Git and Docker on your own machine into a community, rather than imitating a cloud catalog.', meta: 'Perspective · 7 min', link: '/articles/local-first-hub' },
    { title: 'Put another set of eyes before merge', note: 'A strict maintenance flow connecting specialists, a coordinator, and an independent reviewer.', meta: 'Operations · 9 min', link: '/articles/independent-review' },
    { title: 'A Space is an app and a repository', note: 'Why Dockerfile-first unifies Gradio, Next.js, and everything between them.', meta: 'Engineering · 6 min', link: '/articles/docker-spaces' }
  ],
  nodes: [
    { id: '01', title: 'Platform map', note: 'Services, routes, and data boundaries', link: '/wiki/platform-map' },
    { id: '02', title: 'Catalog anatomy', note: 'Models / Datasets / Skills / MCPs', link: '/wiki/catalog' },
    { id: '03', title: 'Runtime', note: 'Spaces / Pages / Actions', link: '/wiki/runtime' },
    { id: '04', title: 'Agent operations', note: 'Delegation, review, and auto-merge', link: '/wiki/agent-operations' },
    { id: '05', title: 'Glossary', note: 'Terms and configuration at a glance', link: '/wiki/glossary' }
  ],
  paths: [
    { label: 'Run it for the first time', detail: 'From Compose up to a verified stack', link: '/guide/getting-started' },
    { label: 'Publish a Space', detail: 'Ship a CPU Docker application', link: '/guide/spaces' },
    { label: 'Design operations', detail: 'Permissions, TLS, and backups', link: '/guide/operations' },
    { label: 'Verify the interface', detail: 'Visual QA across every theme', link: '/guide/visual-qa' }
  ]
})
</script>

<template>
  <main class="atlas-home">
    <section class="atlas-hero">
      <div class="atlas-hero__copy">
        <p class="atlas-eyebrow">{{ copy.eyebrow }}</p>
        <h1>{{ copy.title }}</h1>
        <p class="atlas-hero__lead">{{ copy.lead }}</p>
        <div class="atlas-actions">
          <a class="atlas-button atlas-button--solid" :href="withBase(ja ? '/ja/guide/getting-started' : '/guide/getting-started')">{{ copy.start }} <span>→</span></a>
          <a class="atlas-button" :href="withBase(ja ? '/ja/wiki/' : '/wiki/')">{{ copy.explore }}</a>
        </div>
      </div>
      <div class="atlas-hero__mark" aria-hidden="true">
        <span><img :src="withBase('/pwa-512x512.png')" alt="" style="width:180px;height:180px;object-fit:cover;border-radius:36px;box-shadow:0 18px 48px rgba(6,19,46,.22)"></span>
        <i></i><i></i><i></i>
        <small>LOCAL / GIT / DOCKER</small>
      </div>
    </section>

    <section class="atlas-section atlas-section--articles">
      <header>
        <div><p class="atlas-eyebrow">{{ copy.latest }}</p><h2>{{ copy.sectionRead }}</h2></div>
        <p>{{ copy.sectionReadNote }}</p>
      </header>
      <div class="article-grid">
        <a v-for="(article, index) in copy.articles" :key="article.link" :href="withBase(article.link)" class="article-card">
          <span class="article-card__number">0{{ index + 1 }}</span>
          <p>{{ article.meta }}</p>
          <h3>{{ article.title }}</h3>
          <span>{{ article.note }}</span>
          <b aria-hidden="true">Read ↗</b>
        </a>
      </div>
    </section>

    <section class="atlas-section atlas-section--wiki">
      <header>
        <div><p class="atlas-eyebrow">REFERENCE / CONNECTED</p><h2>{{ copy.sectionWiki }}</h2></div>
        <p>{{ copy.sectionWikiNote }}</p>
      </header>
      <div class="knowledge-map">
        <a v-for="node in copy.nodes" :key="node.id" :href="withBase(node.link)" class="knowledge-node">
          <span>{{ node.id }}</span><strong>{{ node.title }}</strong><small>{{ node.note }}</small><i>↗</i>
        </a>
      </div>
    </section>

    <section class="atlas-section atlas-section--paths">
      <header><div><p class="atlas-eyebrow">START WITH A GOAL</p><h2>{{ copy.sectionPath }}</h2></div></header>
      <nav class="intent-paths" :aria-label="copy.sectionPath">
        <a v-for="path in copy.paths" :key="path.link" :href="withBase(path.link)">
          <strong>{{ path.label }}</strong><span>{{ path.detail }}</span><i>→</i>
        </a>
      </nav>
    </section>
  </main>
</template>
