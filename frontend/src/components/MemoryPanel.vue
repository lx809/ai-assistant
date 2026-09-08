<script setup lang="ts">
import { ref } from "vue";

interface MemoryEntry {
  id: number;
  type: string;
  content: string;
  manual: number;
}

defineProps<{ entries: MemoryEntry[] }>();
const emit = defineEmits<{ save: [id: number, content: string]; remove: [id: number] }>();
const editingId = ref<number | null>(null);
const draft = ref("");
</script>

<template>
  <div class="memory-list">
    <article v-for="entry in entries" :key="entry.id" class="memory-row">
      <div class="memory-meta">
        <span class="type-badge">{{ entry.type }}</span>
        <span v-if="entry.manual" class="manual-badge">手动</span>
      </div>
      <template v-if="editingId === entry.id">
        <textarea v-model="draft" rows="2"></textarea>
        <div class="row-actions">
          <button @click="emit('save', entry.id, draft); editingId = null">保存</button>
          <button class="ghost" @click="editingId = null">取消</button>
        </div>
      </template>
      <template v-else>
        <p>{{ entry.content }}</p>
        <div class="row-actions">
          <button class="ghost" @click="editingId = entry.id; draft = entry.content">编辑</button>
          <button class="danger" @click="emit('remove', entry.id)">删除</button>
        </div>
      </template>
    </article>
    <p v-if="entries.length === 0" class="empty">还没有长期记忆。对助手说“记住……”即可添加。</p>
  </div>
</template>

<style scoped>
.memory-list { display: flex; flex-direction: column; gap: 10px; }
.memory-row { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; }
.memory-meta { display: flex; gap: 8px; margin-bottom: 4px; }
.type-badge { font-size: 12px; background: #e7efff; color: var(--accent); border-radius: 6px; padding: 2px 8px; }
.manual-badge { font-size: 12px; background: #eef2f6; color: var(--muted); border-radius: 6px; padding: 2px 8px; }
textarea { width: 100%; border: 1px solid var(--border); border-radius: 8px; padding: 8px; font: inherit; }
.row-actions { display: flex; gap: 8px; margin-top: 8px; }
button { border: 0; background: var(--accent); color: white; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
button.ghost { background: transparent; color: var(--accent); border: 1px solid var(--border); }
button.danger { background: transparent; color: #b91c1c; border: 1px solid #fecaca; }
.empty { color: var(--muted); text-align: center; }
</style>
