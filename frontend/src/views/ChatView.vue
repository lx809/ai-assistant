<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../lib/api";
import { readChatStream } from "../lib/stream";
import type { ConversationSummary, Message, Source, ToolStep } from "../types";
import ChatMessage from "../components/ChatMessage.vue";
import ConversationList from "../components/ConversationList.vue";

const conversations = ref<ConversationSummary[]>([]);
const activeId = ref<string | null>(null);
const messages = ref<Message[]>([]);
const input = ref("");
const busy = ref(false);
const errorText = ref("");

let currentAssistant: Message | null = null;

function addMessage(role: "user" | "assistant", content = ""): Message {
  const message: Message = { role, content };
  if (role === "assistant") {
    message.tools = [];
    message.sources = [];
    message.done = false;
  }
  messages.value.push(message);
  // 取响应式代理而非原始对象，否则流式追加 token 不会触发视图更新
  const stored = messages.value[messages.value.length - 1];
  if (role === "assistant") currentAssistant = stored;
  return stored;
}

function ensureCurrentAssistant(): Message {
  if (!currentAssistant || currentAssistant.done) {
    return addMessage("assistant");
  }
  return currentAssistant;
}

async function refreshConversations(): Promise<void> {
  conversations.value = await api.listConversations();
}

async function openConversation(id: string): Promise<void> {
  activeId.value = id;
  messages.value = [];
  const resp = await fetch(`/api/conversations/${id}`);
  if (!resp.ok) return;
  const data = (await resp.json()) as { messages: Message[] };
  messages.value = data.messages.map((m) => ({ ...m, tools: [], sources: [], done: true }));
}

function startNew(): void {
  activeId.value = null;
  messages.value = [];
  currentAssistant = null;
}

async function removeConversation(id: string): Promise<void> {
  if (!window.confirm("确定删除这条对话及其全部消息吗？此操作不可恢复。")) return;
  try {
    await api.deleteConversation(id);
    if (activeId.value === id) startNew();
    await refreshConversations();
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "删除失败";
  }
}

async function send(): Promise<void> {
  const text = input.value.trim();
  if (!text || busy.value) return;
  input.value = "";
  busy.value = true;
  errorText.value = "";
  addMessage("user", text);
  try {
    const response = await api.chat(text, activeId.value);
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
    await readChatStream(response, (frame) => {
      const payload = frame.data as Record<string, unknown>;
      if (frame.event === "session_start") {
        activeId.value = String(payload.conversation_id);
        void refreshConversations();
      } else if (frame.event === "token") {
        ensureCurrentAssistant().content += String(payload.text ?? "");
      } else if (frame.event === "tool_start") {
        ensureCurrentAssistant().tools?.push({
          name: String(payload.tool),
          arguments: payload.arguments,
          status: "running",
        } as ToolStep);
      } else if (frame.event === "tool_end") {
        const tools = ensureCurrentAssistant().tools ?? [];
        const step = tools[tools.length - 1];
        if (step) {
          step.status = payload.ok === false ? "failed" : "done";
          step.summary = String(payload.summary ?? "");
        }
      } else if (frame.event === "sources") {
        const list = (payload.sources as Source[]) ?? [];
        ensureCurrentAssistant().sources?.push(...list);
      } else if (frame.event === "error") {
        errorText.value = String(payload.message ?? "发生未知错误");
        if (currentAssistant) currentAssistant.done = true;
      } else if (frame.event === "done") {
        if (currentAssistant) currentAssistant.done = true;
      }
    });
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error);
  } finally {
    if (currentAssistant) currentAssistant.done = true;
    currentAssistant = null;
    busy.value = false;
  }
}

onMounted(refreshConversations);
</script>

<template>
  <main class="chat-layout">
    <ConversationList
      :conversations="conversations"
      :active-id="activeId"
      @create="startNew"
      @select="openConversation"
      @delete="removeConversation"
    />
    <section class="chat-main">
      <div class="messages">
        <ChatMessage v-for="(message, i) in messages" :key="i" :message="message" />
      </div>
      <p v-if="errorText" class="chat-error">{{ errorText }}</p>
      <form class="input-row" @submit.prevent="send">
        <textarea v-model="input" rows="2" placeholder="和你的私人助手聊聊…" @keydown.enter.exact.prevent="send" />
        <button :disabled="busy || !input.trim()">{{ busy ? "思考中…" : "发送" }}</button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.chat-layout { flex: 1; display: flex; min-height: 0; }
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.messages { flex: 1; overflow-y: auto; padding: 0 24px; display: flex; flex-direction: column; }
.chat-error { color: #b91c1c; padding: 0 24px; }
.input-row { display: flex; gap: 10px; padding: 14px 24px; border-top: 1px solid var(--border); background: var(--panel); }
textarea { flex: 1; resize: none; border: 1px solid var(--border); border-radius: 10px; padding: 10px; font: inherit; }
button { border: 0; background: var(--accent); color: white; padding: 0 20px; border-radius: 10px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>


