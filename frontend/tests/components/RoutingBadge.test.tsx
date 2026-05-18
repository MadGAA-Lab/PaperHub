import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RoutingBadge } from "@/components/chat/RoutingBadge";

describe("RoutingBadge", () => {
  it("renders intent label + confidence + tier", () => {
    render(
      <RoutingBadge
        decision={{
          intent: "paper_qa", model_tier: "flagship",
          confidence: 0.92, reasoning: "asks about a paper",
        }}
      />,
    );
    expect(screen.getByText(/paper q&a/i)).toBeInTheDocument();
    expect(screen.getByText(/92/)).toBeInTheDocument();
    expect(screen.getByText(/flagship/i)).toBeInTheDocument();
  });

  it("flags low-confidence (<0.5) with data-conf=\"low\"", () => {
    const { container } = render(
      <RoutingBadge
        decision={{
          intent: "chitchat", model_tier: "small",
          confidence: 0.32, reasoning: "uncertain",
        }}
      />,
    );
    expect(container.querySelector('[data-conf="low"]')).not.toBeNull();
  });

  it("flags high-confidence (>=0.8) with data-conf=\"high\"", () => {
    const { container } = render(
      <RoutingBadge
        decision={{
          intent: "chitchat", model_tier: "small",
          confidence: 0.85, reasoning: "clear greeting",
        }}
      />,
    );
    expect(container.querySelector('[data-conf="high"]')).not.toBeNull();
  });
});
