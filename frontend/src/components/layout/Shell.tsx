import { ReactNode } from "react";

import { useChatStore } from "@/store/chat";
import { cn } from "@/lib/utils";

export function Shell({
  sidebar,
  children,
}: {
  sidebar: ReactNode;
  children: ReactNode;
}) {
  const collapsed = useChatStore((s) => s.sidebarCollapsed);
  return (
    <div
      className={cn(
        "grid h-screen bg-background text-foreground transition-[grid-template-columns] duration-200",
        collapsed ? "grid-cols-[56px_1fr]" : "grid-cols-[260px_1fr]",
      )}
    >
      <aside className="border-r border-border bg-card flex flex-col overflow-hidden">
        {sidebar}
      </aside>
      <main className="flex flex-col min-h-0">{children}</main>
    </div>
  );
}
