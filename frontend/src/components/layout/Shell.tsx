import { ReactNode } from "react";

export function Shell({
  sidebar,
  children,
}: {
  sidebar: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid h-screen grid-cols-[260px_1fr] bg-background text-foreground">
      <aside className="border-r border-border bg-card flex flex-col">
        {sidebar}
      </aside>
      <main className="flex flex-col min-h-0">{children}</main>
    </div>
  );
}
