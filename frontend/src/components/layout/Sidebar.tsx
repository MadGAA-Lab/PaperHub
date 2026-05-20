import {
  BookMarked,
  ChevronsLeft,
  ChevronsRight,
  MessageSquare,
  Plus,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { ReferenceSourcesPanel } from "@/components/references/ReferenceSourcesPanel";
import { deleteBackendSession } from "@/lib/api";
import { useChatStore } from "@/store/chat";

export function Sidebar() {
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const newSession = useChatStore((s) => s.newSession);
  const selectSession = useChatStore((s) => s.selectSession);
  const collapsed = useChatStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);
  const sidebarTab = useChatStore((s) => s.sidebarTab);
  const setSidebarTab = useChatStore((s) => s.setSidebarTab);

  // Count references for the active session to drive the tab badge.
  const referencesBySession = useChatStore((s) => s.referencesBySession);
  const activeBackendId =
    activeSessionId !== null
      ? (sessions.find((s) => s.id === activeSessionId)?.backend_session_id ?? null)
      : null;
  const refsCount =
    activeBackendId !== null
      ? (referencesBySession[activeBackendId]?.length ?? 0)
      : 0;

  const handleDelete = (e: React.MouseEvent, sessionId: number) => {
    e.stopPropagation();
    const currentSessions = useChatStore.getState().sessions;
    const idx = currentSessions.findIndex((s) => s.id === sessionId);
    const removed = useChatStore.getState().deleteSession(sessionId);
    if (!removed) return;

    const backendSessionId = removed.backend_session_id;

    let undone = false;
    toast("Chat deleted", {
      description: removed.title,
      action: {
        label: "Undo",
        onClick: () => {
          undone = true;
          useChatStore.getState().restoreSession(removed, idx);
        },
      },
      duration: 5000,
      onAutoClose: () => {
        if (undone || backendSessionId == null) return;
        void deleteBackendSession(backendSessionId).catch((err: unknown) => {
          toast.error("Failed to delete chat on server", {
            description: err instanceof Error ? err.message : String(err),
          });
        });
      },
    });
  };

  const isMac =
    typeof navigator !== "undefined" &&
    navigator.userAgent.toLowerCase().includes("mac");
  const kbdNew = isMac ? "⌘K" : "Ctrl+K";

  // Each tab gets its own click-to-expand icon when collapsed.
  const expandToTab = (tab: "chats" | "references") => {
    setSidebarTab(tab);
    if (collapsed) toggleSidebar();
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border">
        {!collapsed && <span className="text-lg font-semibold">PaperHub</span>}
        <div className="flex items-center gap-1 ml-auto">
          {!collapsed && <ThemeToggle />}
          <Button
            variant="ghost"
            size="icon"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={toggleSidebar}
          >
            {collapsed ? (
              <ChevronsRight className="h-4 w-4" />
            ) : (
              <ChevronsLeft className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {collapsed ? (
        /* Collapsed: vertical icon rail.  Each icon both selects the tab AND
           expands the sidebar so the user always lands in the right view. */
        <div className="p-2 flex flex-col gap-1">
          <Button
            size="icon"
            variant={sidebarTab === "chats" ? "default" : "ghost"}
            onClick={() => expandToTab("chats")}
            aria-label="Chats"
            aria-current={sidebarTab === "chats" ? "page" : undefined}
            className="w-full"
          >
            <MessageSquare className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant={sidebarTab === "references" ? "default" : "ghost"}
            onClick={() => expandToTab("references")}
            aria-label={`References${refsCount > 0 ? ` (${refsCount.toString()})` : ""}`}
            aria-current={sidebarTab === "references" ? "page" : undefined}
            className="w-full"
          >
            <BookMarked className="h-4 w-4" />
          </Button>
        </div>
      ) : (
        <>
          {/* Tab bar — single source of truth for which view is active. */}
          <div
            role="tablist"
            aria-label="Sidebar sections"
            className="flex border-b border-border"
          >
            <button
              type="button"
              role="tab"
              aria-selected={sidebarTab === "chats"}
              onClick={() => setSidebarTab("chats")}
              className={`flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                sidebarTab === "chats"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Chats
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={sidebarTab === "references"}
              onClick={() => setSidebarTab("references")}
              className={`flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                sidebarTab === "references"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <BookMarked className="h-3.5 w-3.5" />
              References
              {refsCount > 0 && (
                <span className="ml-0.5 inline-flex items-center justify-center min-w-[1.25rem] h-4 rounded-full bg-muted px-1 text-[10px] tabular-nums">
                  {refsCount}
                </span>
              )}
            </button>
          </div>

          {/* Tab content */}
          {sidebarTab === "chats" ? (
            <>
              <div className="p-3">
                <Button
                  variant="secondary"
                  className="w-full justify-start gap-2"
                  onClick={() => newSession()}
                >
                  <Plus className="h-4 w-4" /> New chat
                  <kbd className="ml-auto text-[10px] text-muted-foreground border rounded px-1 py-0.5">
                    {kbdNew}
                  </kbd>
                </Button>
              </div>
              <nav className="flex-1 overflow-y-auto px-2 pb-4">
                {sessions.length === 0 && (
                  <p className="px-2 text-sm text-muted-foreground">
                    No chats yet.
                  </p>
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
            </>
          ) : (
            <div className="flex-1 min-h-0">
              <ReferenceSourcesPanel frontendSessionId={activeSessionId} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
