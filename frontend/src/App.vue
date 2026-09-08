<script setup lang="ts">
import ChatView from "./views/ChatView.vue";
import DocumentsView from "./views/DocumentsView.vue";
import MemoryView from "./views/MemoryView.vue";
import { ref } from "vue";

const tab = ref<"chat" | "documents" | "memory">("chat");
</script>

<template>
  <div class="app-shell">
    <nav class="topnav">
      <button :class="{ active: tab === 'chat' }" @click="tab = 'chat'">对话</button>
      <button :class="{ active: tab === 'documents' }" @click="tab = 'documents'">知识库</button>
      <button :class="{ active: tab === 'memory' }" @click="tab = 'memory'">长期记忆</button>
    </nav>
    <ChatView v-if="tab === 'chat'" />
    <DocumentsView v-else-if="tab === 'documents'" />
    <MemoryView v-else />
  </div>
</template>
