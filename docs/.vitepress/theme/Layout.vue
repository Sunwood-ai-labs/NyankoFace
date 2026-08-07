<script setup lang="ts">
import DefaultTheme from 'vitepress/theme'
import DocContext from './components/DocContext.vue'
import RelatedKnowledge from './components/RelatedKnowledge.vue'

const { Layout } = DefaultTheme
</script>

<template>
  <Layout>
    <template #doc-before>
      <DocContext />
    </template>
    <template #doc-after>
      <RelatedKnowledge />
    </template>
  </Layout>
</template>
