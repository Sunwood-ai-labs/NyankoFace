<script setup lang="ts">
import { computed } from 'vue'
import { useData, withBase } from 'vitepress'

type RelatedItem = { title: string; link: string; note?: string }
const { frontmatter, lang } = useData()
const items = computed<RelatedItem[]>(() => frontmatter.value.related ?? [])
const title = computed(() => lang.value.startsWith('ja') ? '次にたどる知識' : 'Continue through the atlas')
</script>

<template>
  <aside v-if="items.length" class="related-knowledge" aria-labelledby="related-knowledge-title">
    <p class="related-knowledge__eyebrow">RELATED</p>
    <h2 id="related-knowledge-title">{{ title }}</h2>
    <div class="related-knowledge__grid">
      <a v-for="item in items" :key="item.link" :href="withBase(item.link)">
        <strong>{{ item.title }}</strong>
        <span v-if="item.note">{{ item.note }}</span>
        <i aria-hidden="true">↗</i>
      </a>
    </div>
  </aside>
</template>
