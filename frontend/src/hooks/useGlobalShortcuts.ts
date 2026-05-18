import { useEffect } from "react";
import { useTheme } from "next-themes";

import { useChatStore } from "@/store/chat";

type ThemeChoice = "light" | "dark" | "system";

export function useGlobalShortcuts() {
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;

      // Cmd/Ctrl+K — new chat
      if (meta && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        useChatStore.getState().newSession();
        return;
      }

      // Cmd/Ctrl+/ — focus composer
      if (meta && !e.shiftKey && e.key === "/") {
        e.preventDefault();
        const textarea = document.querySelector<HTMLTextAreaElement>(
          "textarea[aria-label='Message']",
        );
        textarea?.focus();
        return;
      }

      // Cmd/Ctrl+Shift+L — cycle theme
      if (meta && e.shiftKey && e.key.toLowerCase() === "l") {
        e.preventDefault();
        const current = (theme as ThemeChoice | undefined) ?? "system";
        const next: ThemeChoice =
          current === "light"
            ? "dark"
            : current === "dark"
              ? "system"
              : "light";
        setTheme(next);
        return;
      }

      // Esc — blur active textarea
      if (e.key === "Escape") {
        const active = document.activeElement as HTMLElement | null;
        if (active?.tagName === "TEXTAREA") {
          active.blur();
        }
      }
    };

    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [theme, setTheme]);
}
