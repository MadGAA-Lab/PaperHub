interface Props {
  /** Accessible label for the status region. Defaults to "Loading". */
  ariaLabel?: string;
  /** Extra Tailwind classes applied to the wrapper element. */
  className?: string;
}

/**
 * Three-dot pulse indicator used for loading states and streaming pre-token
 * wait states.
 */
export function LoadingDots({ ariaLabel = "Loading", className }: Props) {
  return (
    <div
      role="status"
      aria-label={ariaLabel}
      className={`flex items-center gap-1 py-1 ${className ?? ""}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse" />
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse [animation-delay:200ms]" />
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse [animation-delay:400ms]" />
    </div>
  );
}
