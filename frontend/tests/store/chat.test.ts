import { describe, expect, it } from "vitest";
import { useChatStore } from "@/store/chat";

describe("chat store", () => {
  it("starts with no active session", () => {
    useChatStore.getState().reset();
    expect(useChatStore.getState().activeSessionId).toBeNull();
  });

  it("creates a new session and selects it", () => {
    useChatStore.getState().reset();
    const id = useChatStore.getState().newSession();
    expect(id).toBeGreaterThan(0);
    expect(useChatStore.getState().activeSessionId).toBe(id);
  });

  it("appends a user message to the active session", () => {
    useChatStore.getState().reset();
    const id = useChatStore.getState().newSession();
    useChatStore.getState().appendMessage(id, {
      role: "user", content: "hello", run_id: null,
    });
    const session = useChatStore.getState().sessions.find((s) => s.id === id);
    expect(session).toBeDefined();
    expect(session!.messages).toHaveLength(1);
    expect(session!.messages[0]!.content).toBe("hello");
  });
});
