import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { useChatStore } from "@/store/chat";

export function Sidebar() {
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const newSession = useChatStore((s) => s.newSession);
  const selectSession = useChatStore((s) => s.selectSession);

  const handleDelete = (e: React.MouseEvent, sessionId: number) => {
    e.stopPropagation();
    const currentSessions = useChatStore.getState().sessions;
    const idx = currentSessions.findIndex((s) => s.id === sessionId);
    const removed = useChatStore.getState().deleteSession(sessionId);
    if (!removed) return;
    toast("Chat deleted", {
      description: removed.title,
      action: {
        label: "Undo",
        onClick: () =>
          useChatStore.getState().restoreSession(removed, idx),
      },
      duration: 5000,
    });
  };

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
      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {sessions.length === 0 && (
          <p className="px-2 text-sm text-muted-foreground">No chats yet.</p>
        )}
        {sessions.length > 0 && (
          <ul className="space-y-1">
            {sessions.map((s) => {
              const isActive = s.id === activeSessionId;
              return (
                <li key={s.id} className="group/row relative">
                  <button
                    onClick={() => selectSession(s.id)}
                    aria-current={isActive ? "page" : undefined}
                    className={`w-full text-left text-sm rounded-md px-3 py-2 pr-8 transition-colors ${
                      isActive
                        ? "bg-accent text-accent-foreground"
                        : "hover:bg-accent/50 text-foreground"
                    }`}
                  >
                    {s.title}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => handleDelete(e, s.id)}
                    aria-label={`Delete chat: ${s.title}`}
                    className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 transition-opacity p-1 rounded hover:bg-destructive/10"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>
    </div>
  );
}
