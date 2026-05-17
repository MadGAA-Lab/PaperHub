import { create } from "zustand";
import type {
  ChatMessage,
  ChatSession,
  RoutingDecision,
  ToolCallRecord,
} from "@/types/domain";

interface ChatState {
  sessions: ChatSession[];
  activeSessionId: number | null;
  newSession: () => number;
  selectSession: (id: number) => void;
  appendMessage: (sessionId: number, message: ChatMessage) => void;
  setRouting: (sessionId: number, run_id: number, decision: RoutingDecision) => void;
  appendToken: (sessionId: number, run_id: number, text: string) => void;
  appendTrace: (sessionId: number, run_id: number, record: ToolCallRecord) => void;
  finaliseMessage: (sessionId: number, run_id: number, content: string) => void;
  errorMessage: (sessionId: number, run_id: number, error: string) => void;
  failPendingAssistant: (sessionId: number, error: string) => void;
  patchAssistantRunId: (sessionId: number, runId: number) => void;
  reset: () => void;
}

const nextId = (() => {
  let n = 0;
  return () => ++n;
})();

export const useChatStore = create<ChatState>((set) => ({
  sessions: [],
  activeSessionId: null,

  newSession: () => {
    const id = nextId();
    set((s) => ({
      sessions: [...s.sessions, { id, title: "New chat", messages: [] }],
      activeSessionId: id,
    }));
    return id;
  },

  selectSession: (id) => set({ activeSessionId: id }),

  appendMessage: (sessionId, message) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? { ...sess, messages: [...sess.messages, message] }
          : sess,
      ),
    })),

  setRouting: (sessionId, run_id, decision) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, routing_decision: decision }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  appendToken: (sessionId, run_id, text) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, content: m.content + text }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  appendTrace: (sessionId, run_id, record) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, trace: [...(m.trace ?? []), record] }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  finaliseMessage: (sessionId, run_id, content) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, content, status: "ok" }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  errorMessage: (sessionId, run_id, error) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, status: "error", error }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  failPendingAssistant: (sessionId, error) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m, i, arr) =>
                i === arr.length - 1
                  && m.role === "assistant"
                  && (m.status === "streaming" || m.status === undefined)
                  ? { ...m, status: "error", error }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  patchAssistantRunId: (sessionId, runId) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m, i, arr) =>
                i === arr.length - 1 && m.role === "assistant" && m.run_id === null
                  ? { ...m, run_id: runId }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  reset: () => set({ sessions: [], activeSessionId: null }),
}));
