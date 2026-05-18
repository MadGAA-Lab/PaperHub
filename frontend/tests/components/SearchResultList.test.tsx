import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { SearchResultList } from "@/components/chat/SearchResultList";
import { useChatStore } from "@/store/chat";
import { API_BASE_URL } from "@/lib/api";
import type { ReferenceItem, SearchResultCandidate } from "@/types/domain";

function makeCandidate(
  overrides: Partial<SearchResultCandidate> = {},
): SearchResultCandidate {
  return {
    paper_id: "arxiv:1706.03762",
    title: "Attention Is All You Need",
    authors: ["Vaswani", "Shazeer", "Parmar"],
    year: 2017,
    abstract: "The dominant sequence transduction models...",
    arxiv_id: "1706.03762",
    has_open_pdf: true,
    reason: "Foundational transformer paper",
    finalize: false,
    auto_added: false,
    papers_id: null,
    error: null,
    already_in_session: false,
    ...overrides,
  };
}

const ingestResponse = {
  paper_content_id: 1,
  papers_id: 1,
  cache_hit: false,
  title: "Attention Is All You Need",
};

const sampleRefList: ReferenceItem[] = [
  {
    papers_id: 1,
    paper_content_id: 1,
    enabled: true,
    added_at: "2024-01-01T00:00:00",
    arxiv_id: "1706.03762",
    title: "Attention Is All You Need",
    year: 2017,
    kind: "arxiv",
  },
];

const server = setupServer(
  http.post(`${API_BASE_URL}/papers`, () =>
    HttpResponse.json(ingestResponse, { status: 201 }),
  ),
  http.get(`${API_BASE_URL}/papers`, () =>
    HttpResponse.json(sampleRefList),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  server.resetHandlers();
  useChatStore.getState().reset();
});

describe("SearchResultList", () => {
  it("renders nothing when candidates array is empty", () => {
    const { container } = render(
      <SearchResultList candidates={[]} sessionId={1} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders a card for each candidate with title, authors, year", () => {
    const candidates = [
      makeCandidate({ paper_id: "arxiv:1706.03762", title: "Paper A", year: 2017 }),
      makeCandidate({ paper_id: "arxiv:2005.14165", title: "Paper B", year: 2020 }),
    ];
    render(<SearchResultList candidates={candidates} sessionId={1} />);
    expect(screen.getByText("Paper A")).toBeInTheDocument();
    expect(screen.getByText("Paper B")).toBeInTheDocument();
    expect(screen.getByText("2017")).toBeInTheDocument();
    expect(screen.getByText("2020")).toBeInTheDocument();
  });

  it("shows 'Added by agent' badge when auto_added=true", () => {
    render(
      <SearchResultList
        candidates={[makeCandidate({ auto_added: true })]}
        sessionId={1}
      />,
    );
    expect(screen.getByText(/added by agent/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add as reference/i })).toBeNull();
  });

  it("shows 'Source unavailable' disabled button when error=no_ingestible_source", () => {
    render(
      <SearchResultList
        candidates={[makeCandidate({ error: "no_ingestible_source" })]}
        sessionId={1}
      />,
    );
    const btn = screen.getByRole("button", { name: /source unavailable/i });
    expect(btn).toBeDisabled();
  });

  it("calls POST /papers and marks paper added on Add button click", async () => {
    render(
      <SearchResultList
        candidates={[makeCandidate()]}
        sessionId={1}
      />,
    );
    const addBtn = screen.getByRole("button", { name: /add as reference/i });
    await userEvent.click(addBtn);

    await waitFor(() => {
      // After successful add, "Added" badge appears
      expect(screen.getByText(/added/i)).toBeInTheDocument();
    });

    // Store marks the paper id as added
    expect(
      useChatStore.getState().addedPaperIds.has("arxiv:1706.03762"),
    ).toBe(true);
  });

  it("refreshes session references after successful add", async () => {
    render(
      <SearchResultList
        candidates={[makeCandidate()]}
        sessionId={1}
      />,
    );
    const addBtn = screen.getByRole("button", { name: /add as reference/i });
    await userEvent.click(addBtn);

    // After the add resolves, the store should have the fetched reference list
    await waitFor(() => {
      expect(
        useChatStore.getState().referencesBySession[1],
      ).toEqual(sampleRefList);
    });
  });

  it("sends candidate metadata in POST /papers body", async () => {
    // Intercept the POST and capture the parsed body.
    const capturedBodies: unknown[] = [];
    server.use(
      http.post(`${API_BASE_URL}/papers`, async ({ request }) => {
        capturedBodies.push(await request.json());
        return HttpResponse.json(ingestResponse, { status: 201 });
      }),
    );

    const candidate = makeCandidate({
      paper_id: "arxiv:1706.03762",
      title: "Attention Is All You Need",
      abstract: "The dominant sequence transduction models...",
      authors: ["Vaswani", "Shazeer", "Parmar"],
      year: 2017,
    });

    render(<SearchResultList candidates={[candidate]} sessionId={1} />);
    const addBtn = screen.getByRole("button", { name: /add as reference/i });
    await userEvent.click(addBtn);

    await waitFor(() => expect(capturedBodies.length).toBeGreaterThan(0));

    const body = capturedBodies[0] as Record<string, unknown>;
    expect(body.paper_id).toBe("arxiv:1706.03762");
    expect(body.title).toBe("Attention Is All You Need");
    expect(body.abstract).toBe("The dominant sequence transduction models...");
    expect(body.authors).toEqual(["Vaswani", "Shazeer", "Parmar"]);
    expect(body.year).toBe(2017);
  });
});
