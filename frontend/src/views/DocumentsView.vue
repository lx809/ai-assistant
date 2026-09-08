<script setup lang="ts">
import { onMounted, ref } from "vue";
import { documentsApi, type DocumentItem } from "../lib/api";

const items = ref<DocumentItem[]>([]);
const uploading = ref(false);
const scanning = ref(false);
const messageText = ref("");
const fileInput = ref<HTMLInputElement | null>(null);

async function refresh(): Promise<void> {
  items.value = await documentsApi.list();
}

async function uploadFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  uploading.value = true;
  messageText.value = "";
  try {
    await documentsApi.upload(file);
    messageText.value = `已加入索引队列：${file.name}`;
    await refresh();
  } catch (error) {
    messageText.value = error instanceof Error ? error.message : "上传失败";
  } finally {
    uploading.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}

async function scan(): Promise<void> {
  scanning.value = true;
  messageText.value = "";
  try {
    const result = await documentsApi.scan();
    messageText.value = `已扫描 ${result.scanned.length} 个文件`;
    await refresh();
  } finally {
    scanning.value = false;
  }
}

async function remove(id: number): Promise<void> {
  await documentsApi.remove(id);
  await refresh();
}

onMounted(refresh);
</script>

<template>
  <main class="docs-view">
    <h1>知识库</h1>
    <div class="toolbar">
      <input ref="fileInput" type="file" :disabled="uploading" @change="uploadFile" />
      <button :disabled="scanning" @click="scan">{{ scanning ? "扫描中…" : "扫描 knowledge/ 文件夹" }}</button>
    </div>
    <p v-if="messageText" class="docs-message">{{ messageText }}</p>
    <table v-if="items.length">
      <thead>
        <tr><th>文件名</th><th>类型</th><th>状态</th><th>切片数</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="doc in items" :key="doc.id">
          <td :title="doc.path">{{ doc.filename }}</td>
          <td>{{ doc.file_type }}</td>
          <td :class="doc.status">{{ doc.status }}</td>
          <td>{{ doc.chunk_count ?? "-" }}</td>
          <td><button class="danger" @click="remove(doc.id)">删除</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty">还没有文档。上传文件，或把文件放进 knowledge/ 后点击扫描。</p>
  </main>
</template>

<style scoped>
.docs-view { flex: 1; overflow-y: auto; padding: 24px; max-width: 960px; width: 100%; margin: 0 auto; }
h1 { font-size: 20px; }
.toolbar { display: flex; gap: 12px; align-items: center; margin: 12px 0; flex-wrap: wrap; }
button { border: 0; background: var(--accent); color: white; border-radius: 8px; padding: 8px 14px; cursor: pointer; }
button.danger { background: transparent; color: #b91c1c; border: 1px solid #fecaca; }
button:disabled { opacity: 0.6; }
table { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
td.status.completed { color: #15803d; }
td.status.failed { color: #b91c1c; }
td.status.indexing, td.status.pending { color: #b45309; }
.docs-message { color: #15803d; }
.empty { color: var(--muted); }
</style>
