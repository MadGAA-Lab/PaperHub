/**
 * Normalize a one-line ```sql fenced block into a proper multi-line fence.
 *
 * The library_stats agent is told to append the executed query inside a ```sql
 * fenced block, but the model sometimes puts the opening fence, the SQL, and
 * the closing fence ALL ON ONE LINE:
 *
 *   ```sql SELECT id AS paper_content_id, title FROM paper_content ... ```
 *
 * That is not a valid CommonMark fenced block (the fences must be on their own
 * lines), so react-markdown renders it broken and the SqlCard's `language-sql`
 * detection misses it. Rewriting it to a real multi-line fence lets the
 * existing pre→SqlCard path handle it. A correctly-formatted multi-line fence
 * (a newline after ```sql) is left untouched — the `[ \t]+` after the open
 * fence only matches the same-line (broken) shape.
 */
export function liftSqlFence(content: string): string {
  return content.replace(
    /```sql[ \t]+([^\n]*?)[ \t]*```/gi,
    (_match, sql: string) => `\n\n\`\`\`sql\n${sql.trim()}\n\`\`\`\n`,
  );
}
