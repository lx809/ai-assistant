<script setup lang="ts">
import type { Source } from "../types";

defineProps<{ source: Source }>();
</script>

<template>
  <details class="source-card">
    <summary>{{ source.title }}（相似度 {{ source.score }}）</summary>
    <p class="source-path">{{ source.path }}</p>
    <blockquote>{{ source.excerpt }}</blockquote>
  </details>
</template>

<style scoped>
.source-card { border-left: 3px solid var(--accent); background: #f0f6ff; border-radius: 6px; padding: 6px 10px; margin-top: 6px; font-size: 13px; }
.source-path { color: var(--muted); word-break: break-all; }
blockquote { margin: 4px 0 0; color: #374151; white-space: pre-wrap; }
</style>
