<script setup lang="ts">
import type { ConversationSummary } from "../types";

defineProps<{ conversations: ConversationSummary[]; activeId: string | null }>();
const emit = defineEmits<{
  select: [id: string];
  create: [];
  delete: [id: string];
}>();
</script>

<template>
  <aside class="conv-sidebar">
    <button class="new-conv" @click="emit('create')">＋ 新对话</button>
    <div
      v-for="conv in conversations"
      :key="conv.id"
      class="conv-item"
      :class="{ active: conv.id === activeId }"
      @click="emit('select', conv.id)"
    >
      <span class="conv-title">{{ conv.title }}</span>
      <button
        class="conv-delete"
        title="删除此对话"
        @click.stop="emit('delete', conv.id)"
      >删除</button>
    </div>
  </aside>
</template>

<style scoped>
.conv-sidebar { width: 240px; border-right: 1px solid var(--border); background: var(--panel); padding: 12px; display: flex; flex-direction: column; gap: 6px; overflow-y: auto; }
.new-conv { border: 1px dashed var(--border); background: transparent; padding: 8px; border-radius: 8px; cursor: pointer; }
.conv-item { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 6px 8px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.conv-item:hover { background: #f0f1f3; }
.conv-item.active { background: #e7efff; color: var(--accent); }
.conv-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-delete { border: 0; background: transparent; color: var(--muted); cursor: pointer; font-size: 12px; visibility: hidden; }
.conv-item:hover .conv-delete, .conv-item.active .conv-delete { visibility: visible; }
.conv-delete:hover { color: #b91c1c; }
</style>
