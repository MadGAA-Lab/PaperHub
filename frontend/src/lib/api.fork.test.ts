import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { forkSession } from "@/lib/api";

const server = setupServer(
  http.post("http://localhost:8000/sessions/7/fork", async ({ request }) => {
    const body = (await request.json()) as { run_id: number };
    expect(body.run_id).toBe(42);
    return HttpResponse.json(
      { session_id: 99, forked_message: "explain this", title: "Fork of X" },
      { status: 201 },
    );
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("forkSession", () => {
  it("POSTs the run_id and returns the fork result", async () => {
    const res = await forkSession(7, 42);
    expect(res).toEqual({
      session_id: 99,
      forked_message: "explain this",
      title: "Fork of X",
    });
  });
});
