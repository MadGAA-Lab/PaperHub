import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

describe("Composer slideChip prop", () => {
  it("renders the slide chip when slideChip prop is provided", () => {
    const onToggle = vi.fn();
    render(
      <Composer onSubmit={() => {}} disabled={false}
        slideChip={{ page: 5, attached: true, onToggle }} />,
    );
    expect(screen.getByText(/Slide 5/)).toBeInTheDocument();
  });

  it("omits the slide chip when slideChip is null", () => {
    render(<Composer onSubmit={() => {}} disabled={false} slideChip={null} />);
    expect(screen.queryByText(/Slide/)).not.toBeInTheDocument();
  });
});
