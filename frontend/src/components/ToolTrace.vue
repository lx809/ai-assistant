<script setup lang="ts">
import type { ToolStep } from "../types";

defineProps<{ tools: ToolStep[] }>();
</script>

<template>
  <details v-if="tools.length" class="tool-trace">
    <summary>过程（{{ tools.length }} 次工具调用）</summary>
    <ol>
      <li v-for="(step, i) in tools" :key="i" class="tool-step">
        <span class="tool-name">{{ step.name }}</span>
        <span class="tool-status" :class="step.status">{{ step.status }}</span>
        <div v-if="step.summary" class="tool-summary">{{ step.summary.slice(0, 300) }}</div>
      </li>
    </ol>
  </details>
</template>

<style scoped>
.tool-trace { border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; margin-top: 8px; background: #fafbfc; }
.tool-step { margin: 4px 0; }
.tool-status { font-size: 12px; margin-left: 6px; }
.tool-status.running { color: #b45309; }
.tool-status.done { color: #15803d; }
.tool-status.failed { color: #b91c1c; }
.tool-summary { color: var(--muted); font-size: 12px; white-space: pre-wrap; word-break: break-all; }
</style>
