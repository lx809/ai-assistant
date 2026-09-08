<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../lib/api";
import MemoryPanel from "../components/MemoryPanel.vue";

interface MemoryEntry {
  id: number;
  type: string;
  content: string;
  manual: number;
}

const entries = ref<MemoryEntry[]>([]);
const errorText = ref("");

async function refresh(): Promise<void> {
  entries.value = (await api.listMemory()) as MemoryEntry[];
}

async function saveEntry(id: number, content: string): Promise<void> {
  const type = entries.value.find((e) => e.id === id)?.type ?? "general";
  const resp = await fetch(`/api/memory/entries/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, content }),
  });
  if (!resp.ok) errorText.value = "保存失败";
  await refresh();
}

async function removeEntry(id: number): Promise<void> {
  const resp = await fetch(`/api/memory/entries/${id}`, { method: "DELETE" });
  if (!resp.ok) errorText.value = "删除失败";
  await refresh();
}

onMounted(refresh);
</script>

<template>
  <main class="memory-view">
    <h1>长期记忆</h1>
    <p class="hint">助手会把这些内容在每次对话开始时注入；可随时编辑或删除。</p>
    <p v-if="errorText" class="memory-error">{{ errorText }}</p>
    <MemoryPanel :entries="entries" @save="saveEntry" @remove="removeEntry" />
  </main>
</template>

<style scoped>
.memory-view { flex: 1; overflow-y: auto; padding: 24px; max-width: 860px; width: 100%; margin: 0 auto; }
h1 { font-size: 20px; }
.hint { color: var(--muted); }
.memory-error { color: #b91c1c; }
</style>
