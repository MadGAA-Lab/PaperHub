import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { TraceInline } from "@/components/chat/TraceInline";
import type { ToolCallRecord } from "@/types/domain";

const sampleTrace: ToolCallRecord[] = [
  {
    run_id: 1, branch: "", step_index: 0, parent_step: null,
    agent: "router", tool: "classify", model: "gemini/x",
    args_redacted_json: null, result_summary_json: null,
    latency_ms: 12, token_in: null, token_out: null,
    status: "ok", error: null,
  },
  {
    run_id: 1, branch: "", step_index: 1, parent_step: null,
    agent: "chitchat", tool: "generate", model: "gemini/x",
    args_redacted_json: null, result_summary_json: null,
    latency_ms: 240, token_in: null, token_out: null,
    status: "ok", error: null,
  },
];

describe("TraceInline", () => {
  it("starts collapsed with a step count", () => {
    render(<TraceInline trace={sampleTrace} />);
    expect(screen.getByRole("button", { name: /2 steps/i })).toBeInTheDocument();
    expect(screen.queryByText(/router · classify/i)).not.toBeInTheDocument();
  });

  it("expands to show all steps", async () => {
    render(<TraceInline trace={sampleTrace} />);
    await userEvent.click(screen.getByRole("button", { name: /2 steps/i }));
    expect(screen.getByText(/router · classify/i)).toBeInTheDocument();
    expect(screen.getByText(/chitchat · generate/i)).toBeInTheDocument();
  });

  it("flags an error step with data-status=\"error\"", async () => {
    const errorTrace: ToolCallRecord[] = [
      { ...sampleTrace[0]!, status: "error", error: "boom" },
    ];
    const { container } = render(<TraceInline trace={errorTrace} />);
    await userEvent.click(screen.getByRole("button"));
    expect(container.querySelector('[data-status="error"]')).not.toBeNull();
  });

  it("renders nothing for empty trace", () => {
    const { container } = render(<TraceInline trace={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
