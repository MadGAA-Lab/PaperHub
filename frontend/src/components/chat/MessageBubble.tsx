import { marked } from "marked";

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
          <div
            // Assistant content comes from our own LLM, not user input. Switch
            // to a structured renderer (react-markdown) in Plan D when citation
            // buttons need to be injected.
            dangerouslySetInnerHTML={{
              __html: marked.parse(message.content || " ", { async: false }),
            }}
          />
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
