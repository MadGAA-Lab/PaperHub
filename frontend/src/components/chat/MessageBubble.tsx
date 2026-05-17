import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatMessage } from "@/types/domain";

interface Props { message: ChatMessage; }

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  return (
    <article
      data-role={message.role}
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2 prose prose-sm dark:prose-invert ${
          isUser ? "bg-primary text-primary-foreground" : "bg-card border border-border"
        }`}
      >
        {message.status === "error" ? (
          <p className="text-destructive">{message.error}</p>
        ) : isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          // react-markdown renders to React elements (no dangerouslySetInnerHTML).
          // Raw HTML in source is not rendered as HTML by default — exactly what
          // we want for arbitrary tool-result strings flowing into assistant content.
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content || " "}
          </ReactMarkdown>
        )}
        {message.status === "streaming" && (
          <span aria-label="streaming" className="inline-flex ml-2 gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse" />
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse [animation-delay:120ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse [animation-delay:240ms]" />
          </span>
        )}
      </div>
    </article>
  );
}
