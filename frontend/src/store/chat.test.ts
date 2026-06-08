import { beforeEach, describe, expect, it } from "vitest";

import { useChatStore } from "@/store/chat";

describe("addForkedSession", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
  });

  it("adds a backend-of-record session, selects it, returns its local id", () => {
    const localId = useChatStore.getState().addForkedSession(99, "Fork of X");
    const state = useChatStore.getState();
    const sess = state.sessions.find((s) => s.id === localId);
    expect(sess).toBeDefined();
    expect(sess!.backend_session_id).toBe(99);
    expect(sess!.title).toBe("Fork of X");
    expect(sess!.messages).toEqual([]);
    expect(state.activeSessionId).toBe(localId);
  });

  it("does not duplicate when the backend id is already present", () => {
    const first = useChatStore.getState().addForkedSession(99, "Fork of X");
    const second = useChatStore.getState().addForkedSession(99, "Fork of X");
    expect(second).toBe(first);
    const count = useChatStore
      .getState()
      .sessions.filter((s) => s.backend_session_id === 99).length;
    expect(count).toBe(1);
  });
});
