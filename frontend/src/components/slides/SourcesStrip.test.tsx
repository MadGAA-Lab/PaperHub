import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { useCanvasStore } from "@/store/canvas";
import type { SlideSourceSection } from "@/types/domain";

const mockGetPaperSections = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ getPaperSections: mockGetPaperSections }));

import { SourcesStrip } from "./SourcesStrip";

const titleByPaperId = new Map<number, string>([[7, "Attention Is All You Need"]]);

describe("SourcesStrip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCanvasStore.setState({ requestedChunkId: null, requestNonce: 0, open: false });
  });

  it("renders a chip per cited section labelled paper + section", () => {
    const sources: SlideSourceSection[] = [
      { paper_id: 7, section_name: "Introduction", chunk_ids: [101, 102] },
    ];
    render(<SourcesStrip sources={sources} titleByPaperId={titleByPaperId} />);
    const chip = screen.getByRole("button", { name: /Introduction/ });
    expect(chip).toHaveTextContent("Attention Is All You Need");
    expect(chip).toHaveTextContent("Introduction");
  });

  it("opens the Citation Canvas spanning the section's first→last chunk", () => {
    const openSpy = vi.spyOn(useCanvasStore.getState(), "openCitation");
    const sources: SlideSourceSection[] = [
      { paper_id: 7, section_name: "Introduction", chunk_ids: [101, 102] },
    ];
    render(<SourcesStrip sources={sources} titleByPaperId={titleByPaperId} />);
    fireEvent.click(screen.getByRole("button", { name: /Introduction/ }));
    // First + last chunk → the canvas highlights the WHOLE cited section.
    expect(openSpy).toHaveBeenCalledWith(101, 102);
  });

  it("renders an unsourced cite muted + non-clickable", () => {
    const openSpy = vi.spyOn(useCanvasStore.getState(), "openCitation");
    const sources: SlideSourceSection[] = [
      { paper_id: 7, section_name: "Method", chunk_ids: [] },
    ];
    render(<SourcesStrip sources={sources} titleByPaperId={titleByPaperId} />);
    const chip = screen.getByText(/Method/);
    fireEvent.click(chip);
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("falls back to #<paper_id> when the title is unknown", () => {
    const sources: SlideSourceSection[] = [
      { paper_id: 42, section_name: "Results", chunk_ids: [1] },
    ];
    render(<SourcesStrip sources={sources} titleByPaperId={titleByPaperId} />);
    expect(screen.getByRole("button", { name: /Results/ })).toHaveTextContent("#42");
  });

  it("shows a quiet empty state when there are no sources", () => {
    render(<SourcesStrip sources={[]} titleByPaperId={titleByPaperId} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/no single source/i)).toBeInTheDocument();
  });

  // ── edit mode: the per-slide reference editor ──────────────────────────

  it("edit mode: × removes a source via onSetSources", () => {
    const onSetSources = vi.fn();
    const sources: SlideSourceSection[] = [
      { paper_id: 7, section_name: "Introduction", chunk_ids: [101] },
      { paper_id: 7, section_name: "Method", chunk_ids: [200] },
    ];
    render(
      <SourcesStrip
        sources={sources}
        titleByPaperId={titleByPaperId}
        editable
        references={[{ paper_content_id: 7, title: "Attention Is All You Need" }]}
        onSetSources={onSetSources}
      />,
    );
    const removeButtons = screen.getAllByRole("button", { name: /Remove this source/i });
    fireEvent.click(removeButtons[0]!);
    // The remaining source is sent (Introduction removed).
    expect(onSetSources).toHaveBeenCalledWith([
      { paper_id: 7, section_name: "Method" },
    ]);
  });

  it("edit mode: Add source picker resolves sections and adds one", async () => {
    mockGetPaperSections.mockResolvedValue(["Introduction", "Method"]);
    const onSetSources = vi.fn();
    render(
      <SourcesStrip
        sources={[]}
        titleByPaperId={titleByPaperId}
        editable
        references={[{ paper_content_id: 7, title: "Attention Is All You Need" }]}
        onSetSources={onSetSources}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Add source/i }));
    // Pick the paper → sections load from the picker.
    fireEvent.change(screen.getByLabelText(/Select paper/i), {
      target: { value: "7" },
    });
    await waitFor(() => expect(mockGetPaperSections).toHaveBeenCalledWith(7));
    await screen.findByRole("option", { name: "Method" });
    fireEvent.change(screen.getByLabelText(/Select section/i), {
      target: { value: "Method" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Add$/i }));
    expect(onSetSources).toHaveBeenCalledWith([
      { paper_id: 7, section_name: "Method" },
    ]);
  });

  it("edit mode: shows the Add control even when unsourced (synthesis)", () => {
    render(
      <SourcesStrip
        sources={[]}
        titleByPaperId={titleByPaperId}
        editable
        references={[{ paper_content_id: 7, title: "P" }]}
        onSetSources={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /Add source/i })).toBeInTheDocument();
  });
});
