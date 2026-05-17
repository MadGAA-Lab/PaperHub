import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { useChatStore } from "@/store/chat";

export function Sidebar() {
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const newSession = useChatStore((s) => s.newSession);
  const selectSession = useChatStore((s) => s.selectSession);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-4 border-b border-border">
        <span className="text-lg font-semibold">PaperHub</span>
        <ThemeToggle />
      </div>
      <div className="p-3">
        <Button
          variant="default"
          className="w-full justify-start gap-2"
          onClick={() => newSession()}
        >
          <Plus className="h-4 w-4" /> New chat
        </Button>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 pb-4 space-y-1">
        {sessions.length === 0 && (
          <p className="px-2 text-sm text-muted-foreground">No chats yet.</p>
        )}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => selectSession(s.id)}
            className={`w-full text-left text-sm rounded-md px-3 py-2 transition-colors ${
              s.id === activeSessionId
                ? "bg-accent text-accent-foreground"
                : "hover:bg-accent/50 text-foreground"
            }`}
          >
            {s.title}
          </button>
        ))}
      </nav>
    </div>
  );
}
