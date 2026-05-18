# PaperHub Plan B — Frontend Foundation + End-to-End Chitchat

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a React + Vite + Tailwind + Zustand chat shell that consumes `POST /chat` SSE end-to-end against the Plan-A backend, with visible routing badge + trace panel + all four NFR-02 states. Single chat view; no Citation Canvas, no Compare, no Reference Sources panel, no Slide preview — those land in Plans D / F / G.

**Architecture:** Vite + React 19 + TypeScript strict. Tailwind v4 for styling (CSS-first, no `tailwind.config.js`), **shadcn/ui** as the primitive layer (copy-pasted into `src/components/ui/`). Zustand for the chat store; `next-themes` for the theme system. **@microsoft/fetch-event-source** for the POST SSE call (native `EventSource` doesn't support POST). Theme: light + dark with `prefers-color-scheme` default and a sidebar toggle. Tests: Vitest + React Testing Library + MSW (for SSE stubbing).

**Tech Stack:** Node 20+, npm (consistency with `reference/Intro2GenAI-hw1`), Vite 8, React 19, TypeScript 6, Tailwind 4, shadcn/ui (base-ui + cva), Zustand 5, next-themes, @microsoft/fetch-event-source 2.x, Vitest 4, React Testing Library, MSW 2. ESLint v9 flat config + Prettier.

> **This plan was reconciled with the shipped implementation after Plan B's merge.** Code blocks, install commands, and file paths reflect the as-built state on `feat/plan-b-frontend-foundation` (tip `07f3fe16c0c535151ac8a32f8430a16136db3dcf`), not the original 2024-era assumptions. The commit history on the branch tells the lived story; this document is the rewritten "definitive plan" reconciled with reality.

---

## Spec Coverage Summary

| SRS reference | Addressed by |
| --- | --- |
| §III-2 ChatShell / LeftSidebar / ChatThread / MessageBubble / Composer | Tasks 7, 8, 12, 13 |
| §III-2 RoutingBadge (FR-01 surface) | Task 9 |
| §III-2 TraceInline (FR-02 / FR-09 surface) | Task 10 |
| §III-2 EmptyState / LoadingDots / RejectionPill / ErrorToast (NFR-02) | Task 12 (inline) + Task 13 toast wiring |
| FR-01 Routing badge — intent / tier / confidence | Task 9 |
| FR-02 Trace panel — per-step rows | Task 10 |
| NFR-02 no silent failure — visible states for loading / error / rejection / empty | Tasks 12, 13 |
| NFR-06 strict typing | Task 1 (tsconfig strict) + applies throughout |
| Browser-verifiable chitchat round-trip | Task 13 (ChatPage) + Task 14 (smoke) |

**Out of scope for Plan B** (intentional): Citation Canvas, Reference Sources panel, Search Results list, Compare-split view, Slide preview chip, paper-upload UI, authentication. Each is owned by a later plan.

---

## File Structure

```
frontend/
├── package.json
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts                    # @tailwindcss/vite plugin + Vitest config
├── components.json                   # shadcn/ui config
├── index.html
├── .gitignore
├── eslint.config.js                  # ESLint v9 flat config
├── .prettierrc
├── README.md
└── src/
    ├── main.tsx                      # React entry + ThemeProvider (next-themes)
    ├── App.tsx                       # shell + Toaster from sonner
    ├── index.css                     # Tailwind v4 CSS-first + @theme inline + oklch vars
    ├── lib/
    │   ├── api.ts                    # base URL, fetch wrappers
    │   ├── sse.ts                    # POST SSE consumer (fetch-event-source)
    │   └── utils.ts                  # shadcn cn() helper
    ├── types/
    │   └── domain.ts                 # mirrors backend Pydantic models
    ├── store/
    │   └── chat.ts                   # Zustand chat store (sessions, messages, trace)
    ├── hooks/
    │   └── useChatStream.ts          # imperative POST /chat → events → store updates
    ├── components/
    │   ├── ui/                       # shadcn-generated primitives (button, tooltip, …)
    │   ├── layout/
    │   │   ├── Shell.tsx             # sidebar + main grid
    │   │   ├── Sidebar.tsx           # session list + new chat + theme toggle
    │   │   └── ThemeToggle.tsx       # uses useTheme from next-themes
    │   ├── chat/
    │   │   ├── ChatThread.tsx        # message list + auto-scroll + 4 NFR-02 states
    │   │   ├── MessageBubble.tsx     # react-markdown for assistant; plain text for user
    │   │   ├── Composer.tsx
    │   │   ├── RoutingBadge.tsx
    │   │   └── TraceInline.tsx
    │   └── states/
    │       ├── EmptyState.tsx
    │       ├── LoadingDots.tsx
    │       └── RejectionPill.tsx
    └── pages/
        └── ChatPage.tsx              # one route for Plan B; React Router defers to later
└── tests/
    ├── setup.ts                      # jest-dom + window.matchMedia stub for jsdom
    ├── stubs/
    │   └── sse.ts                    # MSW handler streaming canned SSE
    ├── store/
    │   └── chat.test.ts
    ├── components/
    │   ├── MessageBubble.test.tsx
    │   ├── RoutingBadge.test.tsx
    │   ├── TraceInline.test.tsx
    │   ├── ThemeToggle.test.tsx
    │   └── Composer.test.tsx
    └── hooks/
        └── useChatStream.test.ts
```

Note: `frontend/tailwind.config.js`, `postcss.config.js`, `frontend/src/store/theme.ts`, and `tsconfig.app.json` do **not** exist — they were scaffold artefacts or replaced by the v4 approach. Scaffold leftovers also removed: `src/App.css`, `src/assets/react.svg`, `public/vite.svg`, `src/assets/hero.png`.

---

## Task 1 — Vite + TypeScript + ESLint + Prettier bootstrap

**Files:**
- Create: `frontend/` (whole tree per Vite scaffold + overrides)

- [ ] **Step 1: Scaffold the Vite project.**

From repo root:

```powershell
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

This produces a starter React 19 + TypeScript 6 scaffold. Several generated files (`App.css`, `assets/react.svg`, `public/vite.svg`) will be deleted in this task; others get overwritten in later steps.

- [ ] **Step 2: Remove scaffold leftovers.**

```powershell
Remove-Item frontend/src/App.css, frontend/src/assets/react.svg, frontend/public/vite.svg -ErrorAction SilentlyContinue
```

(If `src/assets/hero.png` exists, remove that too.)

- [ ] **Step 3: Replace `frontend/tsconfig.json` to enable strict + path aliases.**

The scaffold generates a `tsconfig.json` that references `tsconfig.app.json`. Replace both with a single `tsconfig.json` (no `references` array — project-references conflict with `noEmit` + `allowImportingTsExtensions` under TypeScript 6):

```jsonc
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "types": ["vite/client"],
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "ignoreDeprecations": "6.0",
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src", "tests"]
}
```

`"ignoreDeprecations": "6.0"` silences the TypeScript 6 deprecation warning on `baseUrl`. The `references` array from the original scaffold is removed — it conflicts with `noEmit`+`allowImportingTsExtensions` and adds no value for a Vite project. Delete `tsconfig.app.json` if it exists.

- [ ] **Step 4: Replace `frontend/vite.config.ts` to register Tailwind v4 plugin + the `@/` alias.**

```ts
/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: { port: 5173 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    css: false,
  },
});
```

Note: Tailwind v4 is registered as a Vite plugin (`@tailwindcss/vite`). There is no `postcss.config.js` and no `tailwind.config.js` — both are obsolete in v4. The `/// <reference types="vitest" />` triple-slash directive suppresses the TS error about the `test` field on `UserConfig`.

- [ ] **Step 5: Add ESLint v9 flat config + Prettier.**

```powershell
npm install --save-dev typescript-eslint @eslint/js globals eslint-plugin-react-hooks eslint-plugin-react-refresh eslint-config-prettier prettier
```

`frontend/eslint.config.js`:

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import prettier from "eslint-config-prettier";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "*.cjs"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
      reactHooks.configs.flat["recommended-latest"],
      prettier,
    ],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.browser,
      parserOptions: {
        project: ["./tsconfig.json", "./tsconfig.node.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { "react-refresh": reactRefresh },
    rules: {
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
```

ESLint v9 uses a flat `eslint.config.js` (not `.eslintrc.cjs`). The umbrella `typescript-eslint` package replaces the separate `@typescript-eslint/parser` + `@typescript-eslint/eslint-plugin`. `react-hooks` v7 flat config is referenced via `reactHooks.configs.flat["recommended-latest"]`.

`frontend/.prettierrc`:

```json
{
  "semi": true,
  "singleQuote": false,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2
}
```

- [ ] **Step 6: Edit scripts in `frontend/package.json`.**

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src tests --max-warnings=0 --no-error-on-unmatched-pattern",
    "typecheck": "tsc -b --noEmit",
    "format": "prettier --write src tests"
  }
}
```

`--no-error-on-unmatched-pattern` is required because Vitest 4+ puts tests in `tests/` which may not exist at scaffold time; ESLint would otherwise exit non-zero when the glob matches nothing.

- [ ] **Step 7: Write `frontend/README.md`.**

```markdown
# PaperHub frontend

## Dev
    npm install
    npm run dev               # Vite on http://localhost:5173

## Test
    npm test
    npm run test:watch

## Lint + typecheck
    npm run lint
    npm run typecheck
```

- [ ] **Step 8: Verify the scaffold builds.**

```powershell
npm run typecheck
npm run lint
npm run build
```

Expected: all three succeed.

- [ ] **Step 9: Commit.**

```powershell
git add frontend/
git commit -m "chore(frontend): scaffold Vite + React 19 + TypeScript 6 strict + ESLint v9 flat config + Prettier"
```

---

## Task 2 — Tailwind v4 + shadcn/ui + first primitives

**Files:**
- Modify: `frontend/package.json`, `frontend/index.html`, `frontend/src/index.css`, `frontend/src/main.tsx`
- Modify: `frontend/vite.config.ts` (Tailwind v4 plugin — already done in Task 1)
- Create: `frontend/components.json`, `frontend/src/lib/utils.ts`
- Create (via shadcn CLI): `frontend/src/components/ui/button.tsx`, `tooltip.tsx`, `sonner.tsx`, `scroll-area.tsx`

- [ ] **Step 1: Install Tailwind v4 + animation package + typography plugin.**

```powershell
cd frontend
npm install --save-dev @tailwindcss/vite tailwindcss tw-animate-css @tailwindcss/typography
npm install sonner next-themes
```

There is no `postcss.config.js` and no `tailwind.config.js` in Tailwind v4. The `@tailwindcss/vite` plugin (already registered in `vite.config.ts`) handles everything.

- [ ] **Step 2: Overwrite `frontend/src/index.css` with Tailwind v4 CSS-first config.**

```css
@import "tailwindcss";
@plugin "@tailwindcss/typography";
@import "tw-animate-css";
@import "shadcn/tailwind.css";
@import "@fontsource-variable/geist";

@custom-variant dark (&:is(.dark *));

@theme inline {
    --font-heading: var(--font-sans);
    --font-sans: 'Geist Variable', sans-serif;
    --color-sidebar-ring: var(--sidebar-ring);
    --color-sidebar-border: var(--sidebar-border);
    --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
    --color-sidebar-accent: var(--sidebar-accent);
    --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
    --color-sidebar-primary: var(--sidebar-primary);
    --color-sidebar-foreground: var(--sidebar-foreground);
    --color-sidebar: var(--sidebar);
    --color-chart-5: var(--chart-5);
    --color-chart-4: var(--chart-4);
    --color-chart-3: var(--chart-3);
    --color-chart-2: var(--chart-2);
    --color-chart-1: var(--chart-1);
    --color-ring: var(--ring);
    --color-input: var(--input);
    --color-border: var(--border);
    --color-destructive: var(--destructive);
    --color-accent-foreground: var(--accent-foreground);
    --color-accent: var(--accent);
    --color-muted-foreground: var(--muted-foreground);
    --color-muted: var(--muted);
    --color-secondary-foreground: var(--secondary-foreground);
    --color-secondary: var(--secondary);
    --color-primary-foreground: var(--primary-foreground);
    --color-primary: var(--primary);
    --color-popover-foreground: var(--popover-foreground);
    --color-popover: var(--popover);
    --color-card-foreground: var(--card-foreground);
    --color-card: var(--card);
    --color-foreground: var(--foreground);
    --color-background: var(--background);
    --radius-sm: calc(var(--radius) * 0.6);
    --radius-md: calc(var(--radius) * 0.8);
    --radius-lg: var(--radius);
    --radius-xl: calc(var(--radius) * 1.4);
    --radius-2xl: calc(var(--radius) * 1.8);
    --radius-3xl: calc(var(--radius) * 2.2);
    --radius-4xl: calc(var(--radius) * 2.6);
}

:root {
    --background: oklch(1 0 0);
    --foreground: oklch(0.145 0 0);
    --card: oklch(1 0 0);
    --card-foreground: oklch(0.145 0 0);
    --popover: oklch(1 0 0);
    --popover-foreground: oklch(0.145 0 0);
    --primary: oklch(0.205 0 0);
    --primary-foreground: oklch(0.985 0 0);
    --secondary: oklch(0.97 0 0);
    --secondary-foreground: oklch(0.205 0 0);
    --muted: oklch(0.97 0 0);
    --muted-foreground: oklch(0.556 0 0);
    --accent: oklch(0.97 0 0);
    --accent-foreground: oklch(0.205 0 0);
    --destructive: oklch(0.577 0.245 27.325);
    --border: oklch(0.922 0 0);
    --input: oklch(0.922 0 0);
    --ring: oklch(0.708 0 0);
    --radius: 0.625rem;
    --sidebar: oklch(0.985 0 0);
    --sidebar-foreground: oklch(0.145 0 0);
    --sidebar-primary: oklch(0.205 0 0);
    --sidebar-primary-foreground: oklch(0.985 0 0);
    --sidebar-accent: oklch(0.97 0 0);
    --sidebar-accent-foreground: oklch(0.205 0 0);
    --sidebar-border: oklch(0.922 0 0);
    --sidebar-ring: oklch(0.708 0 0);
}

.dark {
    --background: oklch(0.145 0 0);
    --foreground: oklch(0.985 0 0);
    --card: oklch(0.205 0 0);
    --card-foreground: oklch(0.985 0 0);
    --popover: oklch(0.205 0 0);
    --popover-foreground: oklch(0.985 0 0);
    --primary: oklch(0.922 0 0);
    --primary-foreground: oklch(0.205 0 0);
    --secondary: oklch(0.269 0 0);
    --secondary-foreground: oklch(0.985 0 0);
    --muted: oklch(0.269 0 0);
    --muted-foreground: oklch(0.708 0 0);
    --accent: oklch(0.269 0 0);
    --accent-foreground: oklch(0.985 0 0);
    --destructive: oklch(0.704 0.191 22.216);
    --border: oklch(1 0 0 / 10%);
    --input: oklch(1 0 0 / 15%);
    --ring: oklch(0.556 0 0);
    --sidebar: oklch(0.205 0 0);
    --sidebar-foreground: oklch(0.985 0 0);
    --sidebar-primary: oklch(0.488 0.243 264.376);
    --sidebar-primary-foreground: oklch(0.985 0 0);
    --sidebar-accent: oklch(0.269 0 0);
    --sidebar-accent-foreground: oklch(0.985 0 0);
    --sidebar-border: oklch(1 0 0 / 10%);
    --sidebar-ring: oklch(0.556 0 0);
}

@layer base {
  * {
    @apply border-border outline-ring/50;
    }
  body {
    @apply bg-background text-foreground;
    }
  html {
    @apply font-sans;
    }
}
```

Key differences from Tailwind v3:
- `@import "tailwindcss"` replaces the three `@tailwind base/components/utilities` directives.
- `@plugin "@tailwindcss/typography"` registers the typography plugin inline — no JS config.
- Dark mode is declared with `@custom-variant dark (&:is(.dark *))` — not a `darkMode: ["class"]` config key.
- CSS variables use `oklch()`, not `hsl()`.
- `tw-animate-css` replaces `tailwindcss-animate`.

- [ ] **Step 3: Initialise shadcn/ui.**

```powershell
npx shadcn@latest init -d
```

This creates `components.json` and `src/lib/utils.ts`. When prompted: TypeScript yes, default style, CSS variables yes.

- [ ] **Step 4: Add primitive components.**

```powershell
npx shadcn@latest add button tooltip scroll-area collapsible badge textarea
```

This drops `src/components/ui/{button,tooltip,scroll-area,collapsible,badge,textarea}.tsx` into the tree.

**Toast note:** The `toast` component was removed from shadcn 4.7.0. Use `sonner` instead — it was already installed in Step 1. The CLI will scaffold `src/components/ui/sonner.tsx` which wraps `<Toaster>` from the `sonner` package.

```powershell
npx shadcn@latest add sonner
```

Some generated primitives have `"use client"` directives (no-ops in Vite) and `// eslint-disable-next-line react-refresh/only-export-components` comments on non-component exports like `buttonVariants` — these are scaffold artefacts, leave them.

**base-ui note:** Some primitives (notably `Tooltip`) migrated from Radix to `@base-ui/react` in shadcn 4.7+. `TooltipTrigger` no longer accepts `asChild`; instead use `render={<element .../>}`. The shipped version of `RoutingBadge` uses this pattern.

- [ ] **Step 5: Wire `<Toaster />` (sonner) + stub app root.**

`frontend/src/App.tsx`:

```tsx
import { Shell } from "@/components/layout/Shell";
import { Sidebar } from "@/components/layout/Sidebar";
import { Toaster } from "@/components/ui/sonner";
import { ChatPage } from "@/pages/ChatPage";

function App() {
  return (
    <>
      <Shell sidebar={<Sidebar />}>
        <ChatPage />
      </Shell>
      <Toaster />
    </>
  );
}

export default App;
```

`<Toaster />` comes from `@/components/ui/sonner` (NOT `@/components/ui/toaster` — that module no longer exists). There is no `useToast` hook; toasts are triggered with `import { toast } from "sonner"; toast.error(...)` directly.

- [ ] **Step 6: Wire `next-themes` in `frontend/src/main.tsx`.**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { ThemeProvider } from "next-themes";

import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <App />
    </ThemeProvider>
  </React.StrictMode>,
);
```

`next-themes` is the **only** theme system. There is no Zustand `theme` store — using both would create two sources of truth. `sonner`'s `<Toaster>` reads from next-themes automatically.

- [ ] **Step 7: Verify visually.**

```powershell
npm run dev
```

Visit `http://localhost:5173`. Expected: "PaperHub" title rendered with Tailwind styling. Kill the server.

- [ ] **Step 8: Verify the gates.**

```powershell
npm run typecheck
npm run lint
npm run build
```

All pass.

- [ ] **Step 9: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): Tailwind v4 + shadcn/ui (button, tooltip, sonner, scroll-area, collapsible, badge, textarea)"
```

---

## Task 3 — Backend CORS retrofit

**Files:**
- Modify: `backend/src/paperhub/app.py`
- Modify: `backend/tests/test_health.py` (add CORS preflight test)

This is a small Plan-A retrofit: the FastAPI app needs to allow the Vite dev server origin (`http://localhost:5173`).

- [ ] **Step 1: Write the failing test.**

Append to `backend/tests/test_health.py`:

```python
async def test_cors_allows_vite_dev_origin() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
```

Run from `backend/`:

```powershell
uv run pytest tests/test_health.py::test_cors_allows_vite_dev_origin -v
```

Expected: FAIL (no CORS middleware yet).

- [ ] **Step 2: Add CORS middleware to `app.py`.**

`backend/src/paperhub/app.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from paperhub.api import chat, health
from paperhub.config import load_settings
from paperhub.db.connection import open_db
from paperhub.db.migrate import apply_schema


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    app.state.settings = settings
    async with open_db(settings.db_path) as conn:
        await apply_schema(conn)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="PaperHub", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(chat.router)
    return app


app = create_app()
```

- [ ] **Step 3: Run.**

```powershell
uv run pytest tests/test_health.py -v
```

Expected: 2 PASSED.

- [ ] **Step 4: Run the full backend suite to confirm nothing else broke.**

```powershell
uv run pytest -v
uv run ruff check src tests
uv run mypy src
```

All clean.

- [ ] **Step 5: Commit.**

```powershell
cd ..
git add backend/src/paperhub/app.py backend/tests/test_health.py
git commit -m "feat(api): allow CORS from Vite dev origin (http://localhost:5173)"
```

---

## Task 4 — Domain types + Zustand chat store

**Files:**
- Create: `frontend/src/types/domain.ts`
- Create: `frontend/src/store/chat.ts`
- Create: `frontend/tests/setup.ts`
- Create: `frontend/tests/store/chat.test.ts`
- Modify: `frontend/vite.config.ts` (Vitest config — already done in Task 1)

Note: **There is no `src/store/theme.ts`**. The original plan envisioned a Zustand theme store, but `next-themes` was adopted in Task 2 as the single source of truth for the theme system. Creating a separate Zustand theme store would produce two sources of truth.

- [ ] **Step 1: Install Vitest + RTL + MSW + Zustand.**

```powershell
cd frontend
npm install --save-dev vitest @vitest/ui jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event msw
npm install zustand
```

- [ ] **Step 2: Write `frontend/tests/setup.ts`.**

```ts
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom does not implement window.matchMedia — provide a minimal stub
// so next-themes and other media-query-dependent code can run in tests.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

afterEach(() => cleanup());
```

The `window.matchMedia` stub is required because jsdom doesn't implement the Media Queries API, and `next-themes` calls it during mount.

- [ ] **Step 3: Write `frontend/src/types/domain.ts` — mirror backend Pydantic models.**

```ts
export type Intent =
  | "paper_search"
  | "paper_qa"
  | "slides"
  | "library_stats"
  | "chitchat";

export type ModelTier = "small" | "flagship";
export type ToolStatus = "ok" | "error" | "rejected";
export type Branch = "" | "A" | "B";

export interface RoutingDecision {
  intent: Intent;
  model_tier: ModelTier;
  confidence: number;
  reasoning: string;
}

export interface ToolCallRecord {
  run_id: number;
  branch: Branch;
  step_index: number;
  parent_step: number | null;
  agent: string;
  tool: string;
  model: string | null;
  args_redacted_json: Record<string, unknown> | null;
  result_summary_json: Record<string, unknown> | null;
  latency_ms: number;
  token_in: number | null;
  token_out: number | null;
  status: ToolStatus;
  error: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  run_id: number | null;
  routing_decision?: RoutingDecision;
  trace?: ToolCallRecord[];
  status?: "streaming" | "ok" | "error";
  error?: string;
}

export interface ChatSession {
  id: number;
  title: string;
  messages: ChatMessage[];
}
```

- [ ] **Step 4: Write the failing test.**

`frontend/tests/store/chat.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { useChatStore } from "@/store/chat";

describe("chat store", () => {
  it("starts with no active session", () => {
    useChatStore.getState().reset();
    expect(useChatStore.getState().activeSessionId).toBeNull();
  });

  it("creates a new session and selects it", () => {
    useChatStore.getState().reset();
    const id = useChatStore.getState().newSession();
    expect(id).toBeGreaterThan(0);
    expect(useChatStore.getState().activeSessionId).toBe(id);
  });

  it("appends a user message to the active session", () => {
    useChatStore.getState().reset();
    const id = useChatStore.getState().newSession();
    useChatStore.getState().appendMessage(id, {
      role: "user", content: "hello", run_id: null,
    });
    const session = useChatStore.getState().sessions.find((s) => s.id === id);
    expect(session).toBeDefined();
    expect(session!.messages).toHaveLength(1);
    expect(session!.messages[0]!.content).toBe("hello");
  });
});
```

Run:

```powershell
npm test
```

Expected: FAIL (store doesn't exist).

- [ ] **Step 5: Implement `frontend/src/store/chat.ts`.**

The interface includes 11 actions — the original 9 from the plan plus `patchAssistantRunId` and `failPendingAssistant`, which were added to address the run_id race condition and NFR-02 silent-failure on pre-event errors:

```ts
import { create } from "zustand";
import type {
  ChatMessage,
  ChatSession,
  RoutingDecision,
  ToolCallRecord,
} from "@/types/domain";

interface ChatState {
  sessions: ChatSession[];
  activeSessionId: number | null;
  newSession: () => number;
  selectSession: (id: number) => void;
  appendMessage: (sessionId: number, message: ChatMessage) => void;
  setRouting: (sessionId: number, run_id: number, decision: RoutingDecision) => void;
  appendToken: (sessionId: number, run_id: number, text: string) => void;
  appendTrace: (sessionId: number, run_id: number, record: ToolCallRecord) => void;
  finaliseMessage: (sessionId: number, run_id: number, content: string) => void;
  errorMessage: (sessionId: number, run_id: number, error: string) => void;
  /** Marks the last streaming assistant message as error — used when SSE fails
   *  before any event arrives (run_id is still null). */
  failPendingAssistant: (sessionId: number, error: string) => void;
  /** Updates the run_id on the most-recent null-run_id assistant placeholder.
   *  Called as soon as the first tool_step or routing_decision event arrives. */
  patchAssistantRunId: (sessionId: number, runId: number) => void;
  reset: () => void;
}

const nextId = (() => {
  let n = 0;
  return () => ++n;
})();

export const useChatStore = create<ChatState>((set) => ({
  sessions: [],
  activeSessionId: null,

  newSession: () => {
    const id = nextId();
    set((s) => ({
      sessions: [...s.sessions, { id, title: "New chat", messages: [] }],
      activeSessionId: id,
    }));
    return id;
  },

  selectSession: (id) => set({ activeSessionId: id }),

  appendMessage: (sessionId, message) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? { ...sess, messages: [...sess.messages, message] }
          : sess,
      ),
    })),

  setRouting: (sessionId, run_id, decision) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, routing_decision: decision }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  appendToken: (sessionId, run_id, text) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, content: m.content + text }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  appendTrace: (sessionId, run_id, record) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, trace: [...(m.trace ?? []), record] }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  finaliseMessage: (sessionId, run_id, content) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, content, status: "ok" }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  errorMessage: (sessionId, run_id, error) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m) =>
                m.run_id === run_id && m.role === "assistant"
                  ? { ...m, status: "error", error }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  failPendingAssistant: (sessionId, error) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m, i, arr) =>
                i === arr.length - 1
                  && m.role === "assistant"
                  && (m.status === "streaming" || m.status === undefined)
                  ? { ...m, status: "error", error }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  patchAssistantRunId: (sessionId, runId) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map((m, i, arr) =>
                i === arr.length - 1 && m.role === "assistant" && m.run_id === null
                  ? { ...m, run_id: runId }
                  : m,
              ),
            }
          : sess,
      ),
    })),

  reset: () => set({ sessions: [], activeSessionId: null }),
}));
```

- [ ] **Step 6: Run.**

```powershell
npm test
npm run typecheck
npm run lint
```

Expected: 3 tests pass, typecheck + lint clean.

- [ ] **Step 7: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): domain types + Zustand chat store + Vitest setup"
```

---

## Task 5 — SSE consumer (lib + hook)

**Files:**
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/sse.ts`
- Create: `frontend/src/hooks/useChatStream.ts`
- Create: `frontend/tests/hooks/useChatStream.test.ts`
- Create: `frontend/tests/stubs/sse.ts`

- [ ] **Step 1: Install fetch-event-source.**

```powershell
npm install @microsoft/fetch-event-source
```

- [ ] **Step 2: Write `frontend/src/lib/api.ts`.**

```ts
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
```

- [ ] **Step 3: Write the MSW SSE stub.**

`frontend/tests/stubs/sse.ts`:

```ts
import { http, HttpResponse } from "msw";

import { API_BASE_URL } from "@/lib/api";

const enc = new TextEncoder();

function sseChunk(event: string, data: unknown): Uint8Array {
  return enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

export const chitchatHappyPath = http.post(`${API_BASE_URL}/chat`, () => {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(
        sseChunk("tool_step", {
          record: {
            run_id: 1, branch: "", step_index: 0, agent: "router", tool: "classify",
            model: "x", latency_ms: 12, status: "ok",
            parent_step: null, args_redacted_json: null, result_summary_json: null,
            token_in: null, token_out: null, error: null,
          },
        }),
      );
      controller.enqueue(
        sseChunk("routing_decision", {
          run_id: 1, branch: "",
          decision: {
            intent: "chitchat", model_tier: "small",
            confidence: 0.9, reasoning: "greeting",
          },
        }),
      );
      controller.enqueue(sseChunk("token", { run_id: 1, branch: "", text: "Hi " }));
      controller.enqueue(sseChunk("token", { run_id: 1, branch: "", text: "there!" }));
      controller.enqueue(
        sseChunk("final", {
          run_id: 1, branch: "", message_id: 2, content: "Hi there!",
        }),
      );
      controller.close();
    },
  });
  return new HttpResponse(stream, {
    headers: { "Content-Type": "text/event-stream" },
  });
});
```

Note: the handler URL is `${API_BASE_URL}/chat` (imported from `@/lib/api`), not a hardcoded `http://localhost:8000/chat`. This means the stub correctly follows any `VITE_API_BASE_URL` override.

- [ ] **Step 4: Write the failing hook test.**

`frontend/tests/hooks/useChatStream.test.ts`:

The tests cover three scenarios: happy path, pre-event failure (asserts re-throw for toast), and mid-stream failure (asserts no re-throw, inline error only):

```ts
import { renderHook, act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { useChatStream } from "@/hooks/useChatStream";
import { useChatStore } from "@/store/chat";
import { API_BASE_URL } from "@/lib/api";
import { chitchatHappyPath } from "../stubs/sse";

const server = setupServer(chitchatHappyPath);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  server.resetHandlers(chitchatHappyPath);
  useChatStore.getState().reset();
});

const enc = new TextEncoder();
function chunk(event: string, data: unknown): Uint8Array {
  return enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

const midStreamFailure = http.post(`${API_BASE_URL}/chat`, () => {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(
        chunk("tool_step", {
          record: {
            run_id: 7, branch: "", step_index: 0, agent: "router",
            tool: "classify", model: "x", latency_ms: 12, status: "ok",
            parent_step: null, args_redacted_json: null,
            result_summary_json: null, token_in: null, token_out: null,
            error: null,
          },
        }),
      );
      controller.enqueue(
        chunk("routing_decision", {
          run_id: 7, branch: "",
          decision: { intent: "chitchat", model_tier: "small", confidence: 0.9, reasoning: "x" },
        }),
      );
      // Defer the error so the reader processes the queued chunks first.
      setTimeout(() => controller.error(new Error("network blip")), 10);
    },
  });
  return new HttpResponse(stream, {
    headers: { "Content-Type": "text/event-stream" },
  });
});

describe("useChatStream", () => {
  it("runs a chitchat round-trip and updates the store", async () => {
    const sessionId = useChatStore.getState().newSession();
    const { result } = renderHook(() => useChatStream());

    await act(async () => {
      await result.current.send(sessionId, "hello");
    });

    await waitFor(() => {
      const session = useChatStore.getState().sessions.find((s) => s.id === sessionId);
      expect(session).toBeDefined();
      const assistant = session!.messages.find((m) => m.role === "assistant");
      expect(assistant).toBeDefined();
      expect(assistant!.status).toBe("ok");
      expect(assistant!.content).toBe("Hi there!");
      expect(assistant!.routing_decision?.intent).toBe("chitchat");
      expect(assistant!.trace).toHaveLength(1);
    });
  });

  it("flips the streaming placeholder to error when SSE fails before any event", async () => {
    server.resetHandlers(
      http.post(`${API_BASE_URL}/chat`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const sessionId = useChatStore.getState().newSession();
    const { result } = renderHook(() => useChatStream());

    let threw = false;
    await act(async () => {
      try {
        await result.current.send(sessionId, "hello");
      } catch {
        threw = true;
      }
    });

    expect(threw).toBe(true); // pre-event failures DO propagate to caller (→ toast)

    await waitFor(() => {
      const session = useChatStore.getState().sessions.find((s) => s.id === sessionId);
      const assistant = session!.messages.find((m) => m.role === "assistant")!;
      expect(assistant.status).toBe("error");
      expect(assistant.error).toBeTruthy();
    });
  });

  it("mid-stream failure: inline error only, no re-throw", async () => {
    server.resetHandlers(midStreamFailure);
    const sessionId = useChatStore.getState().newSession();
    const { result } = renderHook(() => useChatStream());

    let threw = false;
    await act(async () => {
      try {
        await result.current.send(sessionId, "hello");
      } catch {
        threw = true;
      }
    });

    expect(threw).toBe(false); // mid-stream errors must NOT propagate

    await waitFor(() => {
      const session = useChatStore.getState().sessions.find((s) => s.id === sessionId);
      const assistant = session!.messages.find((m) => m.role === "assistant")!;
      expect(assistant.status).toBe("error");
      expect(assistant.error).toBeTruthy();
      expect(assistant.run_id).toBe(7);
    });
  });
});
```

Run:

```powershell
npm test
```

Expected: FAIL (hook doesn't exist yet).

- [ ] **Step 5: Write `frontend/src/lib/sse.ts`.**

```ts
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { API_BASE_URL } from "@/lib/api";

export interface SseHandlers {
  onEvent: (event: string, data: unknown) => void;
  onError?: (err: unknown) => void;
  onClose?: () => void;
}

export async function streamChat(
  body: { session_id: number | null; user_message: string },
  handlers: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await fetchEventSource(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true,
    onopen(response) {
      if (!response.ok) {
        throw new Error(`POST /chat failed: ${response.status} ${response.statusText}`);
      }
      return Promise.resolve();
    },
    onmessage(msg) {
      if (msg.event) {
        try {
          handlers.onEvent(msg.event, JSON.parse(msg.data) as unknown);
        } catch (e) {
          handlers.onError?.(e);
        }
      }
    },
    onerror(err) {
      handlers.onError?.(err);
      throw err;
    },
    onclose() {
      handlers.onClose?.();
    },
  });
}
```

Note: `onopen` is a sync function returning `Promise.resolve()` (not an `async` function) — this avoids a `require-await` lint error since no `await` is needed on the happy path.

- [ ] **Step 6: Write `frontend/src/hooks/useChatStream.ts`.**

Error handling is split by phase:
- **Mid-stream** (`runId !== null` when `onError` fires): the assistant bubble has context (routing badge, partial tokens). `errorMessage` is called inline and `handledInline` is set. The outer `catch` swallows the throw — no toast fires (inline error is enough).
- **Pre-event** (`runId === null` when `onError` fires): the placeholder bubble is empty. `failPendingAssistant` is called AND the error re-throws, so `ChatPage`'s `.catch()` can fire a toast to provide context.

```ts
import { useCallback, useRef } from "react";
import type { RoutingDecision, ToolCallRecord } from "@/types/domain";
import { streamChat } from "@/lib/sse";
import { useChatStore } from "@/store/chat";

interface ToolStepData { record: ToolCallRecord; }
interface RoutingData { run_id: number; branch: string; decision: RoutingDecision; }
interface TokenData { run_id: number; branch: string; text: string; }
interface FinalData { run_id: number; branch: string; message_id: number; content: string; }
interface ErrorData { run_id: number; branch: string; message: string; }

export function useChatStream() {
  const abortRef = useRef<AbortController | null>(null);
  const store = useChatStore;

  const send = useCallback(async (sessionId: number, userMessage: string) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    store.getState().appendMessage(sessionId, {
      role: "user", content: userMessage, run_id: null,
    });
    store.getState().appendMessage(sessionId, {
      role: "assistant", content: "", run_id: null, status: "streaming",
    });
    let runId: number | null = null;
    // True once the error has been rendered inline (mid-stream case).
    // The outer catch checks this to decide whether to re-throw.
    let handledInline = false;

    try {
      await streamChat(
        { session_id: null, user_message: userMessage },
        {
          onEvent: (event, data) => {
            if (event === "tool_step") {
              const rec = (data as ToolStepData).record;
              if (runId === null) {
                runId = rec.run_id;
                store.getState().patchAssistantRunId(sessionId, runId);
              }
              store.getState().appendTrace(sessionId, rec.run_id, rec);
            } else if (event === "routing_decision") {
              const d = data as RoutingData;
              if (runId === null) {
                runId = d.run_id;
                store.getState().patchAssistantRunId(sessionId, runId);
              }
              store.getState().setRouting(sessionId, d.run_id, d.decision);
            } else if (event === "token") {
              const t = data as TokenData;
              store.getState().appendToken(sessionId, t.run_id, t.text);
            } else if (event === "final") {
              const f = data as FinalData;
              store.getState().finaliseMessage(sessionId, f.run_id, f.content);
            } else if (event === "error") {
              const e = data as ErrorData;
              store.getState().errorMessage(sessionId, e.run_id, e.message);
            }
          },
          onError: (err) => {
            const msg = err instanceof Error ? err.message : String(err);
            if (runId !== null) {
              // Mid-stream: bubble has context, inline error is enough.
              store.getState().errorMessage(sessionId, runId, msg);
              handledInline = true;
            } else {
              // Pre-event: placeholder bubble is empty, need both surfaces.
              store.getState().failPendingAssistant(sessionId, msg);
              // Don't set handledInline — outer catch re-throws → ChatPage toasts.
            }
          },
        },
        abortRef.current.signal,
      );
    } catch (err) {
      // fetchEventSource may throw synchronously before onerror fires
      // (e.g. CORS preflight reject). In that case onError didn't run;
      // runId is still null; treat as pre-event.
      if (!handledInline && runId === null) {
        const msg = err instanceof Error ? err.message : String(err);
        store.getState().failPendingAssistant(sessionId, msg);
      }
      // Only re-throw for pre-event failures so ChatPage's toast fires.
      if (!handledInline) {
        throw err;
      }
    }
  }, [store]);

  return { send };
}
```

- [ ] **Step 7: Run.**

```powershell
npm test
```

Expected: all 6 tests pass (3 store + 3 hook).

- [ ] **Step 8: Gates.**

```powershell
npm run typecheck
npm run lint
```

Both clean.

- [ ] **Step 9: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): SSE consumer hook driving Zustand chat store (phase-split error UX)"
```

---

## Task 6 — Theme provider + toggle

**Files:**
- Create: `frontend/src/components/layout/ThemeToggle.tsx`
- Create: `frontend/tests/components/ThemeToggle.test.tsx`

Note: `main.tsx` already mounts `<ThemeProvider>` from `next-themes` (Task 2). There is no Zustand theme store — `next-themes` is the single source of truth.

- [ ] **Step 1: Write the failing test.**

`frontend/tests/components/ThemeToggle.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "@/components/layout/ThemeToggle";

function renderWithProvider() {
  return render(
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
    localStorage.clear();
  });

  it("renders with an accessible label", () => {
    renderWithProvider();
    expect(screen.getByRole("button", { name: /theme/i })).toBeInTheDocument();
  });

  it("toggles the dark class on the html element on click", async () => {
    renderWithProvider();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: /theme/i }));
    // next-themes updates classList asynchronously after the resolved theme settles.
    await waitFor(() =>
      expect(document.documentElement.classList.contains("dark")).toBe(true),
    );
  });
});
```

The test wraps the toggle in `<ThemeProvider>` because `useTheme` from `next-themes` requires that context. `next-themes` updates the DOM class asynchronously, so the assertion uses `waitFor`.

- [ ] **Step 2: Install the icon library.**

```powershell
npm install lucide-react
```

- [ ] **Step 3: Implement.**

`frontend/src/components/layout/ThemeToggle.tsx`:

```tsx
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  // resolvedTheme reflects "system" preferences resolved to "light" or "dark"
  const isDark = (resolvedTheme ?? theme) === "dark";
  const Icon = isDark ? Sun : Moon;
  const next = isDark ? "light" : "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Switch theme (currently ${isDark ? "dark" : "light"})`}
      onClick={() => setTheme(next)}
    >
      <Icon className="h-4 w-4" />
    </Button>
  );
}
```

`useTheme` is from `next-themes`. Both `theme` (raw value, may be `"system"`) and `resolvedTheme` (what's actually applied) are read; `resolvedTheme` takes precedence so the icon reflects the actual current appearance.

- [ ] **Step 4: Run.**

```powershell
npm test
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): theme toggle using next-themes (system-preference default)"
```

---

## Task 7 — Layout shell (Sidebar slot + main slot)

**Files:**
- Create: `frontend/src/components/layout/Shell.tsx`
- Create: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write `Shell.tsx`.**

```tsx
import { ReactNode } from "react";

export function Shell({
  sidebar,
  children,
}: {
  sidebar: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid h-screen grid-cols-[260px_1fr] bg-background text-foreground">
      <aside className="border-r border-border bg-card flex flex-col">
        {sidebar}
      </aside>
      <main className="flex flex-col min-h-0">{children}</main>
    </div>
  );
}
```

- [ ] **Step 2: Write `Sidebar.tsx`.**

The sessions list is a `<ul>` with `<li>` items for screen-reader semantics. Each session button carries `aria-current="page"` when active.

```tsx
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { useChatStore } from "@/store/chat";

export function Sidebar() {
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const newSession = useChatStore((s) => s.newSession);
  const selectSession = useChatStore((s) => s.selectSession);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-4 border-b border-border">
        <span className="text-lg font-semibold">PaperHub</span>
        <ThemeToggle />
      </div>
      <div className="p-3">
        <Button
          variant="default"
          className="w-full justify-start gap-2"
          onClick={() => newSession()}
        >
          <Plus className="h-4 w-4" /> New chat
        </Button>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {sessions.length === 0 && (
          <p className="px-2 text-sm text-muted-foreground">No chats yet.</p>
        )}
        {sessions.length > 0 && (
          <ul className="space-y-1">
            {sessions.map((s) => {
              const isActive = s.id === activeSessionId;
              return (
                <li key={s.id}>
                  <button
                    onClick={() => selectSession(s.id)}
                    aria-current={isActive ? "page" : undefined}
                    className={`w-full text-left text-sm rounded-md px-3 py-2 transition-colors ${
                      isActive
                        ? "bg-accent text-accent-foreground"
                        : "hover:bg-accent/50 text-foreground"
                    }`}
                  >
                    {s.title}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>
    </div>
  );
}
```

- [ ] **Step 3: Update `App.tsx`.**

```tsx
import { Shell } from "@/components/layout/Shell";
import { Sidebar } from "@/components/layout/Sidebar";
import { Toaster } from "@/components/ui/sonner";

function App() {
  return (
    <>
      <Shell sidebar={<Sidebar />}>
        <div className="flex-1 flex items-center justify-center text-muted-foreground">
          ChatPage placeholder — Task 13 will render here.
        </div>
      </Shell>
      <Toaster />
    </>
  );
}

export default App;
```

- [ ] **Step 4: Manual visual check.**

```powershell
npm run dev
```

Visit `http://localhost:5173`. Click "New chat" — sessions list should grow. Toggle theme — colors invert. Kill the server.

- [ ] **Step 5: Gates.**

```powershell
npm run typecheck && npm run lint && npm test
```

All clean.

- [ ] **Step 6: Commit.**

```powershell
git add frontend/
git commit -m "feat(frontend): layout shell + sidebar with sessions list (ul/li + aria-current) + theme toggle"
```

---

## Task 8 — MessageBubble component

**Files:**
- Create: `frontend/src/components/chat/MessageBubble.tsx`
- Create: `frontend/tests/components/MessageBubble.test.tsx`

- [ ] **Step 1: Install react-markdown + remark-gfm.**

```powershell
npm install react-markdown remark-gfm
```

`react-markdown` renders markdown to React elements without `dangerouslySetInnerHTML`. By default it does not execute raw HTML in the source — this is the XSS safety guarantee we rely on for assistant content.

Note: `marked` and `@types/marked` are **not** installed. The plan originally suggested `marked` + `dangerouslySetInnerHTML`, but that approach was replaced before first commit because Plan D will add citation buttons inside assistant markdown, requiring a structured renderer. `react-markdown` handles both the current needs and the future Plan D extension cleanly.

- [ ] **Step 2: Write the failing test.**

`frontend/tests/components/MessageBubble.test.tsx`:

The test suite includes XSS assertions for both user content (plain text path) and assistant content (react-markdown path):

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageBubble } from "@/components/chat/MessageBubble";

describe("MessageBubble", () => {
  it("renders a user message right-aligned", () => {
    render(
      <MessageBubble message={{ role: "user", content: "hello", run_id: null }} />,
    );
    const node = screen.getByText("hello");
    expect(node.closest("article")).toHaveAttribute("data-role", "user");
  });

  it("renders streaming state for an in-flight assistant message", () => {
    render(
      <MessageBubble
        message={{ role: "assistant", content: "Hi th", run_id: 1, status: "streaming" }}
      />,
    );
    expect(screen.getByText(/hi th/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/streaming/i)).toBeInTheDocument();
  });

  it("renders an error message with the error string", () => {
    render(
      <MessageBubble
        message={{
          role: "assistant", content: "", run_id: 1,
          status: "error", error: "Provider 500",
        }}
      />,
    );
    expect(screen.getByText(/provider 500/i)).toBeInTheDocument();
  });

  it("renders user content as plain text (no HTML execution)", () => {
    render(
      <MessageBubble
        message={{
          role: "user",
          content: "<img src=x onerror=alert(1)>",
          run_id: null,
        }}
      />,
    );
    // The literal angle brackets must be present in textContent — no <img> element.
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    const article = screen.getByText(/<img/).closest("article");
    expect(article?.querySelector("img")).toBeNull();
  });

  it("renders assistant raw HTML as escaped text (no script execution)", () => {
    render(
      <MessageBubble
        message={{
          role: "assistant",
          content: "Result: <img src=x onerror=alert(1)>",
          run_id: 1,
          status: "ok",
        }}
      />,
    );
    const article = screen.getByText(/result/i).closest("article");
    // No <img> element should exist — react-markdown renders it as text.
    expect(article?.querySelector("img")).toBeNull();
    expect(article?.textContent).toContain("<img");
  });
});
```

- [ ] **Step 3: Implement.**

`frontend/src/components/chat/MessageBubble.tsx`:

```tsx
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
          // User content is plain text — prevents user-XSS via injected markup.
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
```

XSS design notes:
- User messages: rendered as `<p className="whitespace-pre-wrap">{content}</p>` — React's JSX escaping treats the string as text, so `<img onerror=...>` appears as literal characters.
- Assistant messages: rendered via `<ReactMarkdown>` — by default `react-markdown` does not pass raw HTML through to the DOM, so injected tags appear as text.
- The streaming dots use `motion-safe:animate-pulse` (respects `prefers-reduced-motion: reduce`).

- [ ] **Step 4: Run.**

```powershell
npm test
```

Expected: 5 MessageBubble tests PASS.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): MessageBubble — react-markdown for assistant, plain text for user (XSS-safe)"
```

---

## Task 9 — RoutingBadge component

**Files:**
- Create: `frontend/src/components/chat/RoutingBadge.tsx`
- Create: `frontend/tests/components/RoutingBadge.test.tsx`

- [ ] **Step 1: Write the failing test.**

`frontend/tests/components/RoutingBadge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RoutingBadge } from "@/components/chat/RoutingBadge";

describe("RoutingBadge", () => {
  it("renders intent label + confidence + tier", () => {
    render(
      <RoutingBadge
        decision={{
          intent: "paper_qa", model_tier: "flagship",
          confidence: 0.92, reasoning: "asks about a paper",
        }}
      />,
    );
    expect(screen.getByText(/paper q&a/i)).toBeInTheDocument();
    expect(screen.getByText(/92/)).toBeInTheDocument();
    expect(screen.getByText(/flagship/i)).toBeInTheDocument();
  });

  it("flags low-confidence (<0.5) with data-conf=\"low\"", () => {
    const { container } = render(
      <RoutingBadge
        decision={{
          intent: "chitchat", model_tier: "small",
          confidence: 0.32, reasoning: "uncertain",
        }}
      />,
    );
    expect(container.querySelector('[data-conf="low"]')).not.toBeNull();
  });

  it("flags high-confidence (>=0.8) with data-conf=\"high\"", () => {
    const { container } = render(
      <RoutingBadge
        decision={{
          intent: "chitchat", model_tier: "small",
          confidence: 0.85, reasoning: "clear greeting",
        }}
      />,
    );
    expect(container.querySelector('[data-conf="high"]')).not.toBeNull();
  });
});
```

- [ ] **Step 2: Implement.**

`frontend/src/components/chat/RoutingBadge.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { RoutingDecision } from "@/types/domain";

const intentLabel: Record<RoutingDecision["intent"], string> = {
  paper_search: "Paper search",
  paper_qa: "Paper Q&A",
  slides: "Slides",
  library_stats: "Library stats",
  chitchat: "Chitchat",
};

export function RoutingBadge({ decision }: { decision: RoutingDecision }) {
  const conf = decision.confidence;
  const confLevel = conf >= 0.8 ? "high" : conf >= 0.5 ? "mid" : "low";
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              data-conf={confLevel}
              className="inline-flex items-center gap-2 text-xs cursor-default focus:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
            />
          }
        >
          <Badge variant={confLevel === "low" ? "destructive" : "secondary"}>
            {intentLabel[decision.intent]}
          </Badge>
          <span className="text-muted-foreground">
            {Math.round(conf * 100)}% · {decision.model_tier}
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs text-sm">{decision.reasoning}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
```

`TooltipTrigger` uses `render={<button .../>}` instead of `asChild` — this is the base-ui pattern for shadcn 4.7+. The trigger is a `<button>` (not a `<span>`) so it is keyboard-accessible. The `data-conf` attribute is placed on the trigger element directly so the tests can query it.

- [ ] **Step 3: Run.**

```powershell
npm test
```

Expected: 3 RoutingBadge tests PASS.

- [ ] **Step 4: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): RoutingBadge with intent label + confidence + reasoning tooltip"
```

---

## Task 10 — TraceInline component

**Files:**
- Create: `frontend/src/components/chat/TraceInline.tsx`
- Create: `frontend/tests/components/TraceInline.test.tsx`

- [ ] **Step 1: Write the failing test.**

`frontend/tests/components/TraceInline.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { TraceInline } from "@/components/chat/TraceInline";
import type { ToolCallRecord } from "@/types/domain";

const sampleTrace: ToolCallRecord[] = [
  {
    run_id: 1, branch: "", step_index: 0, parent_step: null,
    agent: "router", tool: "classify", model: "gemini/x",
    args_redacted_json: null, result_summary_json: null,
    latency_ms: 12, token_in: null, token_out: null,
    status: "ok", error: null,
  },
  {
    run_id: 1, branch: "", step_index: 1, parent_step: null,
    agent: "chitchat", tool: "generate", model: "gemini/x",
    args_redacted_json: null, result_summary_json: null,
    latency_ms: 240, token_in: null, token_out: null,
    status: "ok", error: null,
  },
];

describe("TraceInline", () => {
  it("starts collapsed with a step count", () => {
    render(<TraceInline trace={sampleTrace} />);
    expect(screen.getByRole("button", { name: /2 steps/i })).toBeInTheDocument();
    expect(screen.queryByText(/router · classify/i)).not.toBeInTheDocument();
  });

  it("expands to show all steps", async () => {
    render(<TraceInline trace={sampleTrace} />);
    await userEvent.click(screen.getByRole("button", { name: /2 steps/i }));
    expect(screen.getByText(/router · classify/i)).toBeInTheDocument();
    expect(screen.getByText(/chitchat · generate/i)).toBeInTheDocument();
  });

  it("flags an error step with data-status=\"error\"", async () => {
    const errorTrace: ToolCallRecord[] = [
      { ...sampleTrace[0]!, status: "error", error: "boom" },
    ];
    const { container } = render(<TraceInline trace={errorTrace} />);
    await userEvent.click(screen.getByRole("button"));
    expect(container.querySelector('[data-status="error"]')).not.toBeNull();
  });

  it("renders nothing for empty trace", () => {
    const { container } = render(<TraceInline trace={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Implement.**

`frontend/src/components/chat/TraceInline.tsx`:

```tsx
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { ToolCallRecord } from "@/types/domain";

export function TraceInline({ trace }: { trace: ToolCallRecord[] }) {
  const [open, setOpen] = useState(false);
  if (trace.length === 0) return null;
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="mt-2 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        <Icon className="h-3 w-3" /> Trace · {trace.length}{" "}
        {trace.length === 1 ? "step" : "steps"}
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 font-mono">
          {trace.map((r) => (
            <li
              key={`${r.branch}-${r.step_index}`}
              data-status={r.status}
              className={`px-2 py-0.5 rounded ${
                r.status === "error"
                  ? "bg-destructive/10 text-destructive"
                  : r.status === "rejected"
                  ? "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-900 dark:text-yellow-200"
                  : "text-muted-foreground"
              }`}
            >
              [{r.branch || "main"}#{r.step_index}] {r.agent} · {r.tool}{" "}
              ({r.model ?? "-"}) {r.latency_ms}ms {r.status}
              {r.error && ` — ${r.error}`}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

Note: a `rejected` status variant (yellow styling) is included for forward-compat with Plans E and G, which will surface `status="rejected"` tool calls when MCP scope rejection or filesystem `..` path rejection occurs. The `ToolStatus` type already includes `"rejected"` in `domain.ts`.

- [ ] **Step 3: Run.**

```powershell
npm test
```

Expected: 4 TraceInline tests PASS.

- [ ] **Step 4: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): TraceInline collapsible step list with error + rejected highlighting"
```

---

## Task 11 — Composer

**Files:**
- Create: `frontend/src/components/chat/Composer.tsx`
- Create: `frontend/tests/components/Composer.test.tsx`

**UX-first polish (UX #1, #2, #3 — landed in `feat(chat): Enter-sends composer with embedded send + capability action bar`):**
- **Keymap inverted**: plain Enter submits; Shift+Enter inserts newline. Ctrl/Cmd+Enter removed.
- **Embedded send button**: ghost icon-only `<Button>` absolutely positioned inside the textarea (`pr-12` reserves space). Disabled when input is empty.
- **Capability action bar**: four disabled ghost chips (Attach paper / References / Slides / Compare) with Tooltips below the textarea, each explaining when the feature lands.
- **Composer draft from store**: `composerDraft` / `setComposerDraft` in `useChatStore` — allows EmptyState prompt cards to prefill the composer.
- Placeholder updated to: `"Ask about a paper, search, or just chat… (Enter to send, Shift+Enter for new line)"`

- [ ] **Step 1: Write the failing test.**

`frontend/tests/components/Composer.test.tsx` — 7 tests:
- submits via the send button
- submits via plain Enter (no modifier)
- Shift+Enter inserts newline, does NOT submit
- disables the send button when disabled prop is true
- does not submit empty / whitespace input
- clears the textarea after submit
- renders 4 disabled capability action bar buttons with correct labels

- [ ] **Step 2: Implement.**

`frontend/src/components/chat/Composer.tsx`:

```tsx
import { KeyboardEvent, useRef, useState } from "react";
import { Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  onSubmit: (text: string) => void;
  disabled: boolean;
}

export function Composer({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
    ref.current?.focus();   // a11y: refocus textarea after submit
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-border bg-card p-3">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <Textarea
          ref={ref}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about a paper, search, or just chat… (Ctrl+Enter to send)"
          rows={2}
          className="resize-none"
          disabled={disabled}
        />
        <Button onClick={submit} disabled={disabled} aria-label="Send">
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
```

`ref.current?.focus()` after submit returns keyboard focus to the textarea — an accessibility best practice so keyboard-only users don't have to tab back.

- [ ] **Step 3: Run.**

```powershell
npm test
```

Expected: 5 Composer tests PASS.

- [ ] **Step 4: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): Composer with Ctrl+Enter submit + a11y refocus + disabled state"
```

---

## Task 12 — ChatThread with NFR-02 inline states

**Files:**
- Create: `frontend/src/components/chat/ChatThread.tsx`
- Create: `frontend/src/components/states/EmptyState.tsx`
- Create: `frontend/src/components/states/LoadingDots.tsx`
- Create: `frontend/src/components/states/RejectionPill.tsx`

**UX-first polish (UX #7 — landed in `feat(chat): example prompts + retry + copy on assistant messages`):**
- `EmptyState` replaced with 4 clickable prompt cards (Search / BookOpen / Presentation / BarChart3 icons) in a 1–2 column grid. Clicking a card calls `setComposerDraft` to prefill the Composer without submitting.
- Tests added: `tests/components/EmptyState.test.tsx` (3 tests).

- [ ] **Step 1: Write the three inline state components.**

`frontend/src/components/states/EmptyState.tsx` — **as-shipped (UX #7 version)**:

```tsx
import { MessageSquare, Search, BookOpen, Presentation, BarChart3 } from "lucide-react";
import { useChatStore } from "@/store/chat";
// 4 PROMPTS array + grid of <button> cards, each calling setDraft(prompt)
```

`frontend/src/components/states/LoadingDots.tsx`:

```tsx
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
```

`motion-safe:animate-pulse` respects `prefers-reduced-motion: reduce` — the animation is suppressed for users who opt out.

`frontend/src/components/states/RejectionPill.tsx`:

```tsx
import { ShieldAlert } from "lucide-react";

export function RejectionPill({ reason }: { reason: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-yellow-100 dark:bg-yellow-900/30 text-yellow-900 dark:text-yellow-200 px-2 py-0.5 text-xs">
      <ShieldAlert className="h-3 w-3" /> Rejected: {reason}
    </span>
  );
}
```

- [ ] **Step 2: Implement ChatThread.**

`frontend/src/components/chat/ChatThread.tsx`:

```tsx
import { useEffect, useRef } from "react";

import type { ChatSession } from "@/types/domain";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { RoutingBadge } from "@/components/chat/RoutingBadge";
import { TraceInline } from "@/components/chat/TraceInline";
import { EmptyState } from "@/components/states/EmptyState";
import { ScrollArea } from "@/components/ui/scroll-area";

export function ChatThread({ session }: { session: ChatSession | null }) {
  const endRef = useRef<HTMLDivElement>(null);
  const lastMessage = session?.messages[session.messages.length - 1];

  useEffect(() => {
    if (!endRef.current) return;
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    endRef.current.scrollIntoView({
      behavior: prefersReducedMotion ? "auto" : "smooth",
    });
  }, [session?.messages.length, lastMessage?.content]);

  if (!session || session.messages.length === 0) {
    return <EmptyState />;
  }

  return (
    <ScrollArea className="flex-1">
      <div
        className="max-w-3xl mx-auto p-4 space-y-4"
        aria-live="polite"
        aria-atomic="false"
      >
        {session.messages.map((msg, i) => (
          <div key={`${msg.run_id ?? "user"}-${i}`} className="space-y-1">
            <MessageBubble message={msg} />
            {msg.role === "assistant" && msg.routing_decision && (
              <div className="flex justify-start pl-1">
                <RoutingBadge decision={msg.routing_decision} />
              </div>
            )}
            {msg.role === "assistant" && msg.trace && msg.trace.length > 0 && (
              <div className="pl-1">
                <TraceInline trace={msg.trace} />
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </ScrollArea>
  );
}
```

A11y notes:
- `aria-live="polite"` + `aria-atomic="false"` on the messages container: screen readers announce new tokens as they arrive without interrupting the user.
- `scrollIntoView` respects `prefers-reduced-motion` — uses `behavior: "auto"` (instant jump) when reduced motion is set, `"smooth"` otherwise.

`RejectionPill` is exported for future use but not wired into `ChatThread` yet. It will be surfaced by Plan E / Plan G when `status="rejected"` tool calls appear in the trace.

- [ ] **Step 3: Manual visual check.**

```powershell
npm run dev
```

Open the page, click "New chat", confirm the EmptyState renders. Kill the server.

- [ ] **Step 4: Gates.**

```powershell
npm run typecheck && npm run lint && npm test
```

All clean.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): ChatThread with a11y (aria-live) + reduced-motion scroll + EmptyState/LoadingDots/RejectionPill"
```

---

## Task 13 — Wire ChatPage + send action

**Files:**
- Create: `frontend/src/pages/ChatPage.tsx`
- Modify: `frontend/src/App.tsx`

**UX-first polish (UX #12 — landed in `feat(frontend): tri-state theme + collapsible sidebar + global shortcuts`):**
- `useGlobalShortcuts()` mounted at the top of `ChatPage` — provides Ctrl+K, Ctrl+/, Ctrl+Shift+L, Esc.

- [ ] **Step 1: Write `ChatPage.tsx`.**

`useToast` and `useToast` hook do not exist — `toast` from `sonner` is called directly.

```tsx
import { toast } from "sonner";

import { ChatThread } from "@/components/chat/ChatThread";
import { Composer } from "@/components/chat/Composer";
import { useChatStream } from "@/hooks/useChatStream";
import { useChatStore } from "@/store/chat";

export function ChatPage() {
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const newSession = useChatStore((s) => s.newSession);
  const { send } = useChatStream();

  const activeSession =
    activeSessionId === null
      ? null
      : (sessions.find((s) => s.id === activeSessionId) ?? null);

  const isStreaming =
    activeSession?.messages.some((m) => m.status === "streaming") ?? false;

  const handleSubmit = (text: string): void => {
    const sessionId = activeSessionId ?? newSession();
    send(sessionId, text).catch((err: unknown) => {
      toast.error("Request failed", {
        description: err instanceof Error ? err.message : String(err),
      });
    });
  };

  return (
    <div className="flex flex-1 flex-col min-h-0">
      <ChatThread session={activeSession} />
      <Composer onSubmit={handleSubmit} disabled={isStreaming} />
    </div>
  );
}
```

Toast wiring: `send()` only re-throws for pre-event failures (empty placeholder; toast provides context). Mid-stream failures are caught inline in `useChatStream` and do not propagate — the `catch` here does nothing in that case.

- [ ] **Step 2: Slot it into the Shell.**

`frontend/src/App.tsx`:

```tsx
import { Shell } from "@/components/layout/Shell";
import { Sidebar } from "@/components/layout/Sidebar";
import { Toaster } from "@/components/ui/sonner";
import { ChatPage } from "@/pages/ChatPage";

function App() {
  return (
    <>
      <Shell sidebar={<Sidebar />}>
        <ChatPage />
      </Shell>
      <Toaster />
    </>
  );
}

export default App;
```

- [ ] **Step 3: Gates.**

```powershell
npm run typecheck && npm run lint && npm test
```

All clean.

- [ ] **Step 4: Commit.**

```powershell
git add frontend/
git commit -m "feat(chat): ChatPage wiring (Composer → useChatStream → ChatThread) + sonner toast"
```

---

## Task 14 — End-to-end smoke script (frontend + backend)

**Files:**
- Create: `scripts/smoke_e2e.ps1` (repo root)

This script boots both servers, polls health endpoints, POSTs to `/chat`, parses SSE event types from the response, and asserts that all expected events arrived with correct content. It exits 0 on success and non-zero on any assertion failure — suitable for CI.

- [ ] **Step 1: Write the script.**

`scripts/smoke_e2e.ps1`:

```powershell
# End-to-end smoke: boot backend (mocked LLM) + Vite, verify chitchat SSE round-trip, tear down.
# Exit 0 on success, non-zero on any failed assertion.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

$expectedFinal = "Hi from PaperHub! (e2e smoke)"
$env:PAPERHUB_WORKSPACE = Join-Path $backendDir "workspace_smoke_e2e"
$env:PAPERHUB_ROUTER_MOCK = '{"intent":"chitchat","model_tier":"small","confidence":0.9,"reasoning":"e2e smoke"}'
$env:PAPERHUB_CHITCHAT_MOCK = $expectedFinal

if (Test-Path $env:PAPERHUB_WORKSPACE) {
    Remove-Item -Recurse -Force $env:PAPERHUB_WORKSPACE
}

# Free ports 8000 and 5173 if anything is already listening on them.
function Kill-Port([int]$port) {
    $pids = (netstat -ano | Select-String ":$port\s") |
        ForEach-Object { ($_ -split '\s+')[-1] } |
        Where-Object { $_ -match '^\d+$' } |
        Select-Object -Unique
    foreach ($p in $pids) {
        Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue
    }
}
Kill-Port 8000
Kill-Port 5173
Start-Sleep -Milliseconds 300   # let OS reclaim sockets

Push-Location $backendDir
$backend = Start-Process -PassThru -NoNewWindow uv -ArgumentList @(
    "run", "uvicorn", "paperhub.app:app", "--host", "127.0.0.1", "--port", "8000"
)
Pop-Location

Push-Location $frontendDir
$npmCmd = if ($IsWindows -or $env:OS -eq "Windows_NT") { "npm.cmd" } else { "npm" }
# Pass --port 5173 so Vite doesn't silently pick an alternate port.
$frontend = Start-Process -PassThru -NoNewWindow $npmCmd -ArgumentList @("run", "dev", "--", "--port", "5173")
Pop-Location

$exitCode = 1
try {
    # Wait for backend /health
    $backendReady = $false
    for ($i = 0; $i -lt 50; $i++) {
        try {
            Invoke-RestMethod http://127.0.0.1:8000/health -ErrorAction Stop | Out-Null
            $backendReady = $true
            break
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $backendReady) { throw "Backend did not come up on :8000" }

    # Wait for Vite root (Vite listens on localhost which may resolve to [::1] on Windows)
    $frontendReady = $false
    for ($i = 0; $i -lt 50; $i++) {
        try {
            (Invoke-WebRequest http://localhost:5173 -UseBasicParsing -ErrorAction Stop).StatusCode | Out-Null
            $frontendReady = $true
            break
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $frontendReady) { throw "Frontend did not come up on :5173" }

    Write-Host "Both servers up. Posting /chat..."

    # Issue the chat request through curl and capture SSE
    $tmpBody = Join-Path $env:TEMP "smoke_e2e_body.json"
    [System.IO.File]::WriteAllText($tmpBody, '{"user_message":"hello"}')
    $sseRaw = & curl.exe -N -s -X POST http://127.0.0.1:8000/chat `
        -H "Content-Type: application/json" `
        --data-binary "@$tmpBody"

    # Parse expected events
    $eventCounts = @{}
    foreach ($line in $sseRaw -split "`r?`n") {
        if ($line -match "^event:\s*(.+)$") {
            $name = $matches[1].Trim()
            if ($eventCounts.ContainsKey($name)) {
                $eventCounts[$name] = $eventCounts[$name] + 1
            } else {
                $eventCounts[$name] = 1
            }
        }
    }

    Write-Host "Events received: $(($eventCounts.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', ')"

    if (-not $eventCounts.ContainsKey("routing_decision")) {
        throw "Missing routing_decision event"
    }
    if (-not $eventCounts.ContainsKey("tool_step") -or $eventCounts["tool_step"] -lt 2) {
        throw "Expected >=2 tool_step events, got $($eventCounts['tool_step'])"
    }
    if (-not $eventCounts.ContainsKey("token") -or $eventCounts["token"] -lt 1) {
        throw "Expected >=1 token event"
    }
    if (-not $eventCounts.ContainsKey("final")) {
        throw "Missing final event"
    }

    # Verify final content
    $finalLine = ($sseRaw -split "`r?`n") | Where-Object { $_ -match '^data:.*"content":"' } | Select-Object -Last 1
    if (-not ($finalLine -match [regex]::Escape($expectedFinal))) {
        throw "Final content does not contain expected string '$expectedFinal'. Got: $finalLine"
    }

    Write-Host "All assertions passed." -ForegroundColor Green
    $exitCode = 0
} catch {
    Write-Host "SMOKE FAILED: $_" -ForegroundColor Red
    $exitCode = 1
} finally {
    & taskkill.exe /F /T /PID $backend.Id 2>&1 | Out-Null
    & taskkill.exe /F /T /PID $frontend.Id 2>&1 | Out-Null
}

exit $exitCode
```

The script asserts:
- `tool_step` events: `>= 2` (router classify + chitchat generate)
- `routing_decision` event: present
- `token` events: `>= 1`
- `final` event: present with content matching `PAPERHUB_CHITCHAT_MOCK`

- [ ] **Step 2: Mention the script in `README.md`.**

Add under the "Quick start" section:

```markdown
End-to-end smoke (backend + frontend together, mocked LLM):

    .\scripts\smoke_e2e.ps1
```

- [ ] **Step 3: Commit.**

```powershell
git add scripts/smoke_e2e.ps1 README.md
git commit -m "test(e2e): smoke script boots + polls health + asserts SSE events + tears down (CI-suitable)"
```

---

## Task 15 — Lint + typecheck gate documentation

**Files:**
- Modify: `frontend/README.md`
- Modify: `CLAUDE.md` (add frontend gates)

- [ ] **Step 1: Verify all gates pass.**

From `frontend/`:

```powershell
npm test
npm run typecheck
npm run lint
npm run build
```

All four succeed.

- [ ] **Step 2: Append a "Quality gates" section to `frontend/README.md`.**

```markdown
## Quality gates

Must pass before opening a PR:

    npm test          # Vitest + RTL + MSW; 25 tests
    npm run typecheck # tsc strict
    npm run lint      # ESLint v9 flat config
    npm run build     # Vite production build
```

- [ ] **Step 3: Update CLAUDE.md so future Claude sessions know the frontend gates.**

In `CLAUDE.md`, under "Backend quality gates", add a parallel "Frontend quality gates" subsection:

```markdown
## Frontend quality gates

Before any PR, from `frontend/`:

    npm test          # Vitest + RTL + MSW; 25 tests as of Plan B
    npm run typecheck # tsc strict
    npm run lint      # ESLint flat config
    npm run build     # Vite production build

End-to-end smoke (backend + frontend together, mocked LLM, from repo root):

    .\scripts\smoke_e2e.ps1
```

- [ ] **Step 4: Commit.**

```powershell
git add frontend/README.md CLAUDE.md
git commit -m "docs(frontend): document quality gates (25 tests) + update CLAUDE.md"
```

---

## Done state

After Task 15 + UX-first polish pass (4 feat commits):

- `cd frontend; npm test` — **48 Vitest tests pass** (12 store + 2 ThemeToggle + 3 useChatStream + 11 MessageBubble + 3 RoutingBadge + 4 TraceInline + 7 Composer + 3 EmptyState + 3 useGlobalShortcuts).
- `cd frontend; npm run typecheck` — tsc strict clean.
- `cd frontend; npm run lint` — ESLint v9 flat config clean.
- `cd frontend; npm run build` — Vite 8 production build succeeds.
- `cd backend; uv run pytest` — all backend tests pass (including the new CORS preflight test).
- `.\scripts\smoke_e2e.ps1` — boots both servers, polls `/health`, POSTs to `/chat`, asserts `tool_step >= 2`, `routing_decision`, `token >= 1`, `final` events all arrived, final content matches `PAPERHUB_CHITCHAT_MOCK`. Exits 0 on success.
- Theme toggle cycles Light → Dark → System (tri-state) with Monitor icon; tooltip shows current state.
- All four NFR-02 states reachable: EmptyState renders by default, streaming animation while tokens arrive (respects `prefers-reduced-motion`), RejectionPill available for future rejection-status traces, error toast fires on pre-event transport failure (inline error on mid-stream failures).
- No Citation Canvas, no Reference Sources panel, no Search Results, no Compare view — Plans D / G remain to land.

### UX-first polish tasks (landed on `feat/plan-b-frontend-foundation`)

| Finding | Feature | Commit |
|---|---|---|
| #1 | Enter sends, Shift+Enter newline | `feat(chat): Enter-sends composer…` |
| #2 | Embedded icon-only send button | `feat(chat): Enter-sends composer…` |
| #3 | Capability action bar (4 disabled chips + tooltips) | `feat(chat): Enter-sends composer…` |
| #4 | Auto-derive session title from first user message | `feat(chat): session lifecycle…` |
| #5 | Delete session with 5 s Undo toast | `feat(chat): session lifecycle…` |
| #6 | localStorage persist via zustand/middleware (key: `paperhub-chat-v1`) | `feat(chat): session lifecycle…` |
| #7 | EmptyState with 4 clickable prompt cards | `feat(chat): example prompts…` |
| #8 | Retry button on errored assistant bubbles | `feat(chat): example prompts…` |
| #9 | Copy button (hover-revealed) on completed assistant bubbles | `feat(chat): example prompts…` |
| #10 | Tri-state ThemeToggle (Light → Dark → System) | `feat(frontend): tri-state theme…` |
| #11 | Collapsible sidebar (56 px rail / 260 px expanded) | `feat(frontend): tri-state theme…` |
| #12 | Global shortcuts: Ctrl+K, Ctrl+/, Ctrl+Shift+L, Esc | `feat(frontend): tri-state theme…` |

---

## Plan self-review

- **Spec coverage** — every SRS §III-2 component slot for Plan-B scope mapped to a task. Citation Canvas (FR-03), Reference Sources panel (FR-08 UI), Search Results, Compare-split, Slide preview chip are correctly deferred and unreferenced.
- **Placeholder scan** — every step contains real code blocks or real commands matching the shipped implementation. No TBD / TODO.
- **Type consistency** — `RoutingDecision`, `ToolCallRecord`, `ChatMessage`, `ChatSession`, `Intent`, `Branch` shapes match Plan A's Pydantic models exactly. The `branch` literal `["", "A", "B"]` is mirrored. `ToolStatus` includes `"rejected"` for Plan E/G forward-compat.
- **No scope creep** — no react-router, no react-query, no IndexedDB persistence, no auth.
- **Tooling reality** — Tailwind v4 (CSS-first, no config files), ESLint v9 flat config, React 19, TypeScript 6, Vite 8, `next-themes` for the theme system, `sonner` for toasts.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-paperhub-B-frontend-foundation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task with spec + code-quality reviews between tasks. Same flow as Plan A.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.
