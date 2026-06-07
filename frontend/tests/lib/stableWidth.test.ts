import { describe, expect, it } from "vitest";

import { pushWidth } from "@/lib/stableWidth";

describe("pushWidth (issue #6 ResizeObserver flap guard)", () => {
  it("accepts the first sample", () => {
    const { recent, apply } = pushWidth([], 700);
    expect(apply).toBe(true);
    expect(recent).toEqual([700]);
  });

  it("accepts a distinct new width and keeps the last two", () => {
    let r: number[] = [];
    ({ recent: r } = pushWidth(r, 700));
    ({ recent: r } = pushWidth(r, 685));
    const step = pushWidth(r, 670);
    expect(step.apply).toBe(true);
    // keep=2 → only the last two retained.
    expect(step.recent).toEqual([685, 670]);
  });

  it("rejects a width that bounces back (A↔B scrollbar flap) and terminates", () => {
    // Simulate the observer oscillating between 700 (no scrollbar) and 685
    // (scrollbar present): the layout must settle, not toggle forever.
    let r: number[] = [];
    const applied: number[] = [];
    for (const sample of [700, 685, 700, 685, 700, 685]) {
      const step = pushWidth(r, sample);
      r = step.recent;
      if (step.apply) applied.push(sample);
    }
    // Only the first two distinct widths are ever applied; the rest are flaps.
    expect(applied).toEqual([700, 685]);
  });

  it("does not apply when the width is unchanged", () => {
    const step = pushWidth([700, 700], 700);
    expect(step.apply).toBe(false);
  });

  it("allows a genuine monotonic resize drag to keep updating", () => {
    let r: number[] = [];
    const applied: number[] = [];
    for (const sample of [700, 690, 680, 670, 660]) {
      const step = pushWidth(r, sample);
      r = step.recent;
      if (step.apply) applied.push(sample);
    }
    expect(applied).toEqual([700, 690, 680, 670, 660]);
  });
});
