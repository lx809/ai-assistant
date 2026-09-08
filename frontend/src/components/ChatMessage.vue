<script setup lang="ts">
import type { Message } from "../types";
import ToolTrace from "./ToolTrace.vue";
import SourceCard from "./SourceCard.vue";

defineProps<{ message: Message }>();
</script>

<template>
  <article class="message" :class="message.role">
    <div class="bubble">{{ message.content }}<span v-if="message.role === 'assistant' && message.done === false" class="cursor" /></div>
    <template v-if="message.role === 'assistant'">
      <SourceCard v-for="(source, i) in message.sources" :key="i" :source="source" />
      <ToolTrace v-if="message.tools && message.tools.length" :tools="message.tools" />
    </template>
  </article>
</template>

<style scoped>
.message { display: flex; flex-direction: column; margin: 14px 0; max-width: 820px; }
.message.user { align-items: flex-end; }
.bubble { white-space: pre-wrap; line-height: 1.7; padding: 10px 14px; border-radius: 12px; max-width: 100%; word-break: break-word; }
.message.user .bubble { background: var(--accent); color: white; border-bottom-right-radius: 2px; }
.message.assistant .bubble { background: var(--panel); border: 1px solid var(--border); border-bottom-left-radius: 2px; }
.cursor { display: inline-block; width: 7px; height: 1em; margin-left: 2px; vertical-align: text-bottom; background: currentColor; animation: blink 1s steps(2, start) infinite; }
@keyframes blink { to { visibility: hidden; } }
</style>
