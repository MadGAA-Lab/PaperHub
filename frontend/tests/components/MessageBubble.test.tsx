import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageBubble } from "@/components/chat/MessageBubble";

describe("MessageBubble", () => {
  it("renders a user message right-aligned", () => {
    render(
      <MessageBubble message={{ role: "user", content: "hello", run_id: null }} />,
    );
    const node = screen.getByText("hello");
    expect(node.closest("article")).toHaveAttribute("data-role", "user");
  });

  it("renders streaming state for an in-flight assistant message", () => {
    render(
      <MessageBubble
        message={{
          role: "assistant", content: "Hi th", run_id: 1, status: "streaming",
        }}
      />,
    );
    expect(screen.getByText(/hi th/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/streaming/i)).toBeInTheDocument();
  });

  it("renders an error message with the error string", () => {
    render(
      <MessageBubble
        message={{
          role: "assistant", content: "", run_id: 1,
          status: "error", error: "Provider 500",
        }}
      />,
    );
    expect(screen.getByText(/provider 500/i)).toBeInTheDocument();
  });

  it("renders user content as plain text (no HTML execution)", () => {
    render(
      <MessageBubble
        message={{
          role: "user",
          content: "<img src=x onerror=alert(1)>",
          run_id: null,
        }}
      />,
    );
    // The literal angle brackets must be present in textContent — no <img> element.
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    const article = screen.getByText(/<img/).closest("article");
    expect(article?.querySelector("img")).toBeNull();
  });

  it("renders assistant raw HTML as escaped text (no script execution)", () => {
    render(
      <MessageBubble
        message={{
          role: "assistant",
          content: "Result: <img src=x onerror=alert(1)>",
          run_id: 1,
          status: "ok",
        }}
      />,
    );
    const article = screen.getByText(/result/i).closest("article");
    // No <img> element should exist — react-markdown renders it as text.
    expect(article?.querySelector("img")).toBeNull();
    // The literal characters should appear (react-markdown shows them as text).
    expect(article?.textContent).toContain("<img");
  });
});
