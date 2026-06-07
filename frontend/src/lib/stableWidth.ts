/**
 * Suppress the ResizeObserver feedback flap in the slide viewer (issue #6).
 *
 * The main slide area is `overflow-auto` and the rendered page width is derived
 * from its `clientWidth`. At a threshold viewport width the page's rendered
 * height crosses the scroll boundary, so the vertical scrollbar toggles, which
 * changes `clientWidth` by the scrollbar width, which re-renders the page at the
 * new width, which toggles the scrollbar back — an infinite A↔B layout loop.
 *
 * `scrollbar-gutter: stable` removes the cause in modern browsers, but this
 * guard guarantees termination regardless (overlay scrollbars, older engines):
 * a measured width that bounces back to a value held in the recent-applied
 * buffer is treated as oscillation and rejected, while a genuine monotonic
 * resize is always accepted.
 *
 * Pure + immutable so it can be unit-tested deterministically (jsdom has no
 * ResizeObserver, so the real observer loop can't be driven in tests).
 */
export function pushWidth(
  recent: readonly number[],
  next: number,
  keep = 2,
): { recent: number[]; apply: boolean } {
  // A width we recently settled on reappearing means the observer is flapping
  // across a scrollbar threshold — keep the current layout, drop this sample.
  if (recent.includes(next)) {
    return { recent: [...recent], apply: false };
  }
  return { recent: [...recent, next].slice(-keep), apply: true };
}
