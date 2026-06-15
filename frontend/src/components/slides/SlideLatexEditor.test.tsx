import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// CodeMirror's EditorView needs DOM layout APIs jsdom lacks; mock it to a
// plain textarea that preserves the value/onChange contract so the editor's
// surrounding controls are what we test here.
vi.mock("@uiw/react-codemirror", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange?: (v: string) => void;
  }) => (
    <textarea
      aria-label="latex-source"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

import { SlideLatexEditor } from "./SlideLatexEditor";

describe("SlideLatexEditor", () => {
  it("renders the value and reports edits via onChange", () => {
    const onChange = vi.fn();
    render(
      <SlideLatexEditor
        value={"\\begin{frame}x\\end{frame}"}
        onChange={onChange}
        onSave={() => {}}
        onCancel={() => {}}
        scope="frame"
      />,
    );
    const ta = screen.getByLabelText("latex-source");
    expect(ta).toHaveValue("\\begin{frame}x\\end{frame}");
    fireEvent.change(ta, { target: { value: "edited" } });
    expect(onChange).toHaveBeenCalledWith("edited");
  });

  it("shows the frame scope banner", () => {
    render(
      <SlideLatexEditor value="x" onChange={() => {}} onSave={() => {}} onCancel={() => {}} scope="frame" />,
    );
    expect(screen.getByText(/Editing this frame/i)).toBeInTheDocument();
  });

  it("shows the whole-deck scope banner", () => {
    render(
      <SlideLatexEditor value="x" onChange={() => {}} onSave={() => {}} onCancel={() => {}} scope="deck" />,
    );
    expect(screen.getByText(/Editing the whole deck/i)).toBeInTheDocument();
  });

  it("Save calls onSave; both buttons disabled while saving", () => {
    const onSave = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = render(
      <SlideLatexEditor value="x" onChange={() => {}} onSave={onSave} onCancel={onCancel} scope="frame" />,
    );
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalledOnce();

    rerender(
      <SlideLatexEditor value="x" onChange={() => {}} onSave={onSave} onCancel={onCancel} scope="frame" saving />,
    );
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeDisabled();
  });

  it("renders the compile-error log when present", () => {
    render(
      <SlideLatexEditor
        value="x"
        onChange={() => {}}
        onSave={() => {}}
        onCancel={() => {}}
        scope="frame"
        errorLog="! Undefined control sequence."
      />,
    );
    expect(screen.getByText(/Undefined control sequence/)).toBeInTheDocument();
  });
});
