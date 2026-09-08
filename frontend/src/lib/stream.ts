export interface SseEvent {
  event: string;
  data: unknown;
}

export function parseSseBuffer(buffer: string): { frames: SseEvent[]; rest: string } {
  const frames: SseEvent[] = [];
  let rest = buffer;
  while (true) {
    const separator = rest.indexOf("\n\n");
    if (separator === -1) break;
    const block = rest.slice(0, separator);
    rest = rest.slice(separator + 2);
    const lines = block.replace(/\r/g, "").split("\n");
    let event = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length === 0) continue;
    let data: unknown;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      data = dataLines.join("\n");
    }
    frames.push({ event, data });
  }
  return { frames, rest };
}

export async function readChatStream(
  response: Response,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error("浏览器不支持流式读取");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const onAbort = () => {
    void reader.cancel();
  };
  signal?.addEventListener("abort", onAbort);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseBuffer(buffer);
      buffer = parsed.rest;
      for (const frame of parsed.frames) onEvent(frame);
    }
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}
