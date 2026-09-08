export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body.slice(0, 200)}`);
  }
  return (await resp.json()) as T;
}

export const api = {
  listConversations(): Promise<ConversationSummary[]> {
    return request("/api/conversations");
  },
  listMemory(): Promise<Record<string, unknown>[]> {
    return request("/api/memory/entries");
  },
  chat(message: string, conversationId: string | null): Promise<Response> {
    return fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, message }),
    });
  },
  deleteConversation(id: string): Promise<{ ok: boolean }> {
    return request(`/api/conversations/${id}`, { method: "DELETE" });
  },
};

export interface DocumentItem {
  id: number;
  filename: string;
  path: string;
  file_type: string;
  status: string;
  chunk_count: number | null;
  error: string | null;
}

export const documentsApi = {
  list(): Promise<DocumentItem[]> {
    return request("/api/documents");
  },
  upload(file: File): Promise<{ status: string }> {
    const form = new FormData();
    form.append("file", file);
    return request("/api/documents/upload", { method: "POST", body: form });
  },
  scan(): Promise<{ scanned: string[] }> {
    return request("/api/documents/scan", { method: "POST" });
  },
  remove(id: number): Promise<{ ok: boolean }> {
    return request(`/api/documents/${id}`, { method: "DELETE" });
  },
};

