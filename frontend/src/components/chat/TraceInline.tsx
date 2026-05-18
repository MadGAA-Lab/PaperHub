import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { ToolCallRecord } from "@/types/domain";

export function TraceInline({ trace }: { trace: ToolCallRecord[] }) {
  const [open, setOpen] = useState(false);
  if (trace.length === 0) return null;
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="mt-2 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        <Icon className="h-3 w-3" /> Trace · {trace.length}{" "}
        {trace.length === 1 ? "step" : "steps"}
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 font-mono">
          {trace.map((r) => (
            <li
              key={`${r.branch}-${r.step_index}`}
              data-status={r.status}
              className={`px-2 py-0.5 rounded ${
                r.status === "error"
                  ? "bg-destructive/10 text-destructive"
                  : r.status === "rejected"
                  ? "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-900 dark:text-yellow-200"
                  : "text-muted-foreground"
              }`}
            >
              [{r.branch || "main"}#{r.step_index}] {r.agent} · {r.tool}{" "}
              ({r.model ?? "-"}) {r.latency_ms}ms {r.status}
              {r.error && ` — ${r.error}`}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
