import { useTranslation } from "react-i18next";

import { useCanvasStore } from "@/store/canvas";

interface Props {
  chunkId: number;
  ordinal: number;
}

/** Academic-style superscript citation. Clicking opens the Citation Canvas
 * on the cited chunk (FR-03). */
export function CitationMarker({ chunkId, ordinal }: Props) {
  const { t } = useTranslation("canvas");
  const openCitation = useCanvasStore((s) => s.openCitation);
  return (
    <sup>
      <button
        type="button"
        aria-label={t("marker.citationAria", { ordinal })}
        onClick={() => openCitation(chunkId)}
        className="mx-0.5 cursor-pointer rounded px-1 text-[0.7em] font-medium text-primary hover:bg-primary/10 hover:underline"
      >
        {ordinal}
      </button>
    </sup>
  );
}
