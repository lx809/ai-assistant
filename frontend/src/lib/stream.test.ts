import { describe, expect, it } from "vitest";
import { parseSseBuffer, type SseEvent } from "./stream";

describe("parseSseBuffer", () => {
  it("解析完整帧并保留半帧", () => {
    const input =
      'event: token\ndata: {"text":"你"}\n\nevent: token\ndata: {"text":"好"}\n\n';
    const result = parseSseBuffer(input);
    expect(result.frames).toHaveLength(2);
    expect(result.frames[0]).toEqual<SseEvent>({ event: "token", data: { text: "你" } });
    expect(result.rest).toBe("");
  });

  it("保留未结束的半帧", () => {
    const result = parseSseBuffer('event: token\ndata: {"text"');
    expect(result.frames).toHaveLength(0);
    expect(result.rest).toContain('"text"');
  });
});

