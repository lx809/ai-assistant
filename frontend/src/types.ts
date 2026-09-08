export interface ToolStep {
  name: string;
  arguments?: unknown;
  summary?: string;
  status: "running" | "done" | "failed";
}

export interface Source {
  document_id: number;
  title: string;
  path: string;
  excerpt: string;
  score: number;
}

export interface Message {
  id?: number;
  role: "user" | "assistant";
  content: string;
  tools?: ToolStep[];
  sources?: Source[];
  done?: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}
