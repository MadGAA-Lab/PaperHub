import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "next-themes";
import { createElement } from "react";

import { useGlobalShortcuts } from "@/hooks/useGlobalShortcuts";
import { useChatStore } from "@/store/chat";

// Wrapper that supplies next-themes context
function wrapper({ children }: { children: React.ReactNode }) {
  return createElement(
    ThemeProvider,
    { attribute: "class", defaultTheme: "light", enableSystem: false },
    children,
  );
}

function fireKey(key: string, opts: Partial<KeyboardEventInit> = {}) {
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key, bubbles: true, ...opts }),
  );
}

beforeEach(() => {
  localStorage.clear();
  useChatStore.getState().reset();
});

describe("useGlobalShortcuts", () => {
  it("Cmd/Ctrl+K creates a new session", () => {
    renderHook(() => useGlobalShortcuts(), { wrapper });
    const before = useChatStore.getState().sessions.length;
    fireKey("k", { ctrlKey: true });
    expect(useChatStore.getState().sessions.length).toBe(before + 1);
  });

  it("Cmd/Ctrl+/ focuses the message textarea", () => {
    // Add a textarea with the expected aria-label to the DOM
    const textarea = document.createElement("textarea");
    textarea.setAttribute("aria-label", "Message");
    document.body.appendChild(textarea);
    const focusSpy = vi.spyOn(textarea, "focus");

    renderHook(() => useGlobalShortcuts(), { wrapper });
    fireKey("/", { ctrlKey: true });

    expect(focusSpy).toHaveBeenCalled();
    document.body.removeChild(textarea);
  });

  it("Esc blurs an active textarea", () => {
    const textarea = document.createElement("textarea");
    document.body.appendChild(textarea);
    textarea.focus();
    // jsdom sets activeElement synchronously
    const blurSpy = vi.spyOn(textarea, "blur");

    renderHook(() => useGlobalShortcuts(), { wrapper });
    fireKey("Escape");

    expect(blurSpy).toHaveBeenCalled();
    document.body.removeChild(textarea);
  });
});
