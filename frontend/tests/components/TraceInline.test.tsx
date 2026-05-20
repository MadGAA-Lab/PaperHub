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

// ---------------------------------------------------------------------------
// Existing tests (preserved)
// ---------------------------------------------------------------------------
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

  // ---------------------------------------------------------------------------
  // New tests — Task v2.4-3
  // ---------------------------------------------------------------------------

  it("test_expand_reveals_reason_prominently", async () => {
    const trace: ToolCallRecord[] = [
      {
        run_id: 2, branch: "", step_index: 0, parent_step: null,
        agent: "research", tool: "paper_search", model: "gpt-4o",
        args_redacted_json: {
          reason: "match the user's query",
          query: "transformers",
        },
        result_summary_json: null,
        latency_ms: 300, token_in: null, token_out: null,
        status: "ok", error: null,
      },
    ];
    render(<TraceInline trace={trace} />);
    // Open outer list
    await userEvent.click(screen.getByRole("button", { name: /1 step/i }));
    // Open row
    const rowButton = screen.getByRole("button", { name: /paper_search/i });
    await userEvent.click(rowButton);
    // "Why:" label and reason text must both be present
    expect(screen.getByText(/Why:/i)).toBeInTheDocument();
    expect(screen.getByText(/match the user's query/i)).toBeInTheDocument();
  });

  it("test_expand_reveals_query_and_result_count", async () => {
    const trace: ToolCallRecord[] = [
      {
        run_id: 3, branch: "", step_index: 0, parent_step: null,
        agent: "research", tool: "search_arxiv", model: "gpt-4o",
        args_redacted_json: { query: "transformer" },
        result_summary_json: { summary: { count: 5 } },
        latency_ms: 500, token_in: null, token_out: null,
        status: "ok", error: null,
      },
    ];
    render(<TraceInline trace={trace} />);
    await userEvent.click(screen.getByRole("button", { name: /1 step/i }));
    const rowButton = screen.getByRole("button", { name: /search_arxiv/i });
    await userEvent.click(rowButton);
    expect(screen.getByText(/transformer/i)).toBeInTheDocument();
    // Match "count: 5" — use a container query to avoid collision with "500ms"
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("test_collapsed_rows_dont_render_args_or_result", async () => {
    const trace: ToolCallRecord[] = [
      {
        run_id: 4, branch: "", step_index: 0, parent_step: null,
        agent: "research", tool: "paper_qa", model: "gpt-4o",
        args_redacted_json: {
          reason: "answer the user question",
          query: "deep learning survey",
        },
        result_summary_json: { summary: { count: 3 } },
        latency_ms: 800, token_in: null, token_out: null,
        status: "ok", error: null,
      },
    ];
    render(<TraceInline trace={trace} />);
    // Open outer list but do NOT click the row
    await userEvent.click(screen.getByRole("button", { name: /1 step/i }));
    // Args/result detail must not be in DOM
    expect(screen.queryByText(/Why:/i)).toBeNull();
    expect(screen.queryByText(/answer the user question/i)).toBeNull();
    expect(screen.queryByText(/deep learning survey/i)).toBeNull();
  });

  it("test_error_row_displays_error_in_red", async () => {
    const errorTrace: ToolCallRecord[] = [
      {
        ...sampleTrace[0]!,
        status: "error",
        error: "connection timeout",
        result_summary_json: { error: "connection timeout" },
      },
    ];
    const { container } = render(<TraceInline trace={errorTrace} />);
    // Open outer list
    await userEvent.click(screen.getByRole("button", { name: /1 step/i }));
    // The li should have error styling
    expect(container.querySelector('[data-status="error"]')).not.toBeNull();
    // Open row to see result detail
    const rowButton = screen.getByRole("button", { name: /classify/i });
    await userEvent.click(rowButton);
    // Error text in red via text-destructive class
    const errorEl = container.querySelector(".text-destructive");
    expect(errorEl).not.toBeNull();
    expect(errorEl!.textContent).toContain("connection timeout");
  });

  it("test_clicking_row_toggles_aria_expanded", async () => {
    const trace: ToolCallRecord[] = [
      {
        run_id: 5, branch: "", step_index: 0, parent_step: null,
        agent: "research", tool: "paper_search", model: "gpt-4o",
        args_redacted_json: { query: "nlp" },
        result_summary_json: null,
        latency_ms: 200, token_in: null, token_out: null,
        status: "ok", error: null,
      },
    ];
    render(<TraceInline trace={trace} />);
    // Open outer list
    await userEvent.click(screen.getByRole("button", { name: /1 step/i }));
    // The per-row button starts collapsed (aria-expanded=false)
    const rowButton = screen.getByRole("button", { name: /paper_search/i });
    expect(rowButton).toHaveAttribute("aria-expanded", "false");
    // Click to expand
    await userEvent.click(rowButton);
    expect(rowButton).toHaveAttribute("aria-expanded", "true");
    // Click again to collapse
    await userEvent.click(rowButton);
    expect(rowButton).toHaveAttribute("aria-expanded", "false");
  });
});
