export function LoadingDots() {
  return (
    <span
      role="status"
      aria-label="Loading"
      className="inline-flex items-center gap-1"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse" />
      <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse [animation-delay:120ms]" />
      <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground motion-safe:animate-pulse [animation-delay:240ms]" />
    </span>
  );
}
