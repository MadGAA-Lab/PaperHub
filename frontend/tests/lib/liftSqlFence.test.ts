import { describe, expect, it } from "vitest";

import { liftSqlFence } from "@/lib/liftSqlFence";

describe("liftSqlFence", () => {
  it("normalizes a one-line ```sql … ``` block (the real model output)", () => {
    // Verbatim from a live library_stats run (run 557): fence + SQL + fence all
    // on one line, which is NOT a valid fenced block.
    const input =
      "Here are the most relevant ones:\n\n```sql SELECT id AS paper_content_id, title, substr(abstract, 1, 200) AS snippet FROM paper_content WHERE title LIKE '%Transformer%' OR abstract LIKE '%Transformer%' ```";
    const out = liftSqlFence(input);
    expect(out).toContain(
      "```sql\nSELECT id AS paper_content_id, title, substr(abstract, 1, 200) AS snippet FROM paper_content WHERE title LIKE '%Transformer%' OR abstract LIKE '%Transformer%'\n```",
    );
    // The broken one-line fence is gone (no ```sql followed by a space).
    expect(out).not.toMatch(/```sql[ \t]/);
  });

  it("leaves a correctly-formatted multi-line ```sql block untouched", () => {
    const input = "answer\n\n```sql\nSELECT year, COUNT(*) FROM paper_content GROUP BY year\n```";
    expect(liftSqlFence(input)).toBe(input);
  });

  it("does not touch a non-sql fenced block", () => {
    const input = "```py\nprint(1)\n```";
    expect(liftSqlFence(input)).toBe(input);
  });

  it("does not touch ordinary prose or inline code", () => {
    const input = "run `npm test` then `npm run build`";
    expect(liftSqlFence(input)).toBe(input);
  });
});
