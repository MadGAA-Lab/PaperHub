import { useMemo } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { StreamLanguage } from "@codemirror/language";
import { stex } from "@codemirror/legacy-modes/mode/stex";
import { useTranslation } from "react-i18next";
import { useTheme } from "next-themes";
import { Check, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  onCancel: () => void;
  /** Which scope is being edited — drives the banner so a whole-deck Save is
   *  never a surprise. */
  scope: "frame" | "deck";
  /** True while a Save → recompile round-trip is in flight (disables both
   *  buttons + the editor). */
  saving?: boolean;
  /** The pdflatex error log from a failed recompile (the edit isn't applied);
   *  shown in a banner so the user can fix the LaTeX and re-Save. */
  errorLog?: string | null;
}

/**
 * SlideLatexEditor — a not-live CodeMirror editor for the deck source. Editing
 * a single frame or the whole `deck.tex`; Save recompiles (the parent owns the
 * round-trip). A scope banner states what will be saved; a failed compile's log
 * renders inline while the last-good PDF stays on screen behind the editor.
 */
export function SlideLatexEditor({
  value,
  onChange,
  onSave,
  onCancel,
  scope,
  saving = false,
  errorLog,
}: Props) {
  const { t } = useTranslation("slides");
  const { resolvedTheme } = useTheme();
  const extensions = useMemo(() => [StreamLanguage.define(stex)], []);

  return (
    <div className="flex flex-1 min-h-0 flex-col bg-card">
      {/* Header: scope banner + Save / Cancel */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border shrink-0">
        <span className="text-xs font-medium text-muted-foreground truncate">
          {scope === "frame"
            ? t("editor.scopeFrame", "Editing this frame")
            : t("editor.scopeDeck", "Editing the whole deck")}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            aria-label={t("editor.cancel", "Cancel")}
            onClick={onCancel}
            disabled={saving}
          >
            <X className="h-3 w-3" />
          </Button>
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            aria-label={t("editor.save", "Save & recompile")}
            className="text-primary"
            onClick={onSave}
            disabled={saving}
          >
            {saving ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Check className="h-3 w-3" />
            )}
          </Button>
        </div>
      </div>

      {/* Compile-error banner — the edit was NOT applied; last-good PDF stands. */}
      {errorLog && (
        <div
          role="alert"
          className="shrink-0 max-h-32 overflow-auto border-b border-destructive/40 bg-destructive/10 px-3 py-2"
        >
          <p className="mb-1 text-xs font-semibold text-destructive">
            {t("editor.compileError", "Compile failed — fix the LaTeX and save again")}
          </p>
          <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-snug text-destructive/90">
            {errorLog}
          </pre>
        </div>
      )}

      {/* The editor fills the rest and scrolls internally. */}
      <div className="flex-1 min-h-0 overflow-auto">
        <CodeMirror
          value={value}
          onChange={onChange}
          editable={!saving}
          theme={resolvedTheme === "dark" ? "dark" : "light"}
          extensions={extensions}
          height="100%"
          basicSetup={{ lineNumbers: true, foldGutter: true }}
        />
      </div>
    </div>
  );
}
