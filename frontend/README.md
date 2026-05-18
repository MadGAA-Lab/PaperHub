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

## Format
    npm run format            # Prettier write src tests

## Build
    npm run build
    npm run preview           # serve the production build locally

## Quality gates

Must pass before opening a PR:

    npm test          # Vitest + RTL + MSW
    npm run typecheck # tsc strict
    npm run lint      # ESLint flat config
    npm run build     # Vite production build
