# Tribe dashboard (web/)

The dashboard. Next.js 16 App Router, Tailwind v4, shadcn/ui (radix,
Nova), Geist via next/font (the `geist` package, self-hosted). Read `AGENTS.md` first: this
Next.js has Cache Components on.

```
npm run dev                         # fixtures mode (synthetic data) unless TRIBE_DATA_SOURCE=db
npm run lint && npm run typecheck   # ESLint (react/jsx-no-literals on) and tsc
npm run build                       # TRIBE_DATA_SOURCE=fixtures for the first deploy
npm run test:e2e                    # Playwright, installed Chrome, 390px and 1280px
npm run gen:hosted                  # after a strategist/hosted_schema change
python -m strategist.test_web_copy  # from the repo root: copy rules, literals, leaks
```

## Rules for every screen

- **Text:** all UI text lives in `copy/en.json`. Use `copy.x.y`, `t("x.y")` or `fmt(copy.x, {n})`
  from `lib/copy.ts`. Each screen adds keys only under its own namespace (`board`, `reel`,
  `patterns`, `lab`, `settings`). Never "views", "viral", "score", rank numbers or a winner; say
  "plays"; FLAT not LOW; no pronouns for creators; no em dashes. `test_web_copy` checks it.
- **Layers:** every rendered value carries `data-layer` (`counts`, `facts`, `shape`, `brain`,
  `ui`). Use `LayerValue` / `ShapeChip` / `TimeChip`. The layer of each page field is in the
  generated types (`lib/hosted.gen.ts`, `/** layer: ... */`). Counts and brain never share a line,
  sort, chart, total or card (D20); `tests/shell.spec.ts` checks the whole document, the shell
  included. The freshness lines are one per layer: stacked in the sidebar from 768px, one
  "Counts as of …" line that opens to the rest on a phone.
- **Data:** read through `lib/data.ts` only, from a server component inside `<Suspense>`
  (see `app/board/page.tsx`). Pages are checked against the hosted schemas before use.
- **Jobs:** `JobButton` (kind from `contracts/job-kinds.json`, label from copy). Disabled kinds
  show their stage; paid kinds show "about $X" (disabled or not) and open `ConfirmJobDialog`.
- **Look:** tokens in `app/globals.css` (`bg-canvas`, `bg-surface`, `bg-subtle`, `border-line`,
  `text-muted-foreground`, `text-indigo-accent` for selection / focus / "Claude suggested" only).
  The default Tailwind palette is cleared on purpose. Rows `h-9 pointer-coarse:h-11`, radius
  `rounded-md` on controls and `rounded-xl` (8px) on cards, borders not shadows. Every `Button`
  size is 44px tall on touch; a small control that keeps its look (a chip, a tick, an inline link)
  takes `tap-target` (a 44px ::before hit area on touch; never on an element that clips its
  overflow). Merge classes with `cn` from `lib/utils.ts` only: it knows `text-ui` and `text-mono`
  are font sizes.
- **Ownership:** each screen owns `app/<route>/**` and `components/<screen>/**`. Shared files
  (`components/shared`, `components/shell`, `components/ui`, `lib`, `copy` outside your
  namespace, `contracts`, `db`, `fixtures`) are changed by the foundation owner.

## Env

| Name | Where | What |
|---|---|---|
| `TRIBE_DATA_SOURCE` | Vercel | `db` to read Postgres; anything else reads `fixtures/` |
| `TRIBE_WEB_DATABASE_URL` | Vercel, Sensitive | the `tribe_web` role (`db/roles.sql`). Never `DATABASE_URL`: the Neon integration fills that with the owner role, so it is connected to Development only and the code ignores it |
| `KV_REST_API_URL` / `KV_REST_API_TOKEN` (or `UPSTASH_REDIS_REST_*`) | Vercel | the runner wake list and heartbeat (`contracts/runner.json`) |
| `TRIBE_OWNER_DATABASE_URL` | your shell only | `npm run db:migrate` (files only, never `drizzle-kit push`) |

`.vercelignore` is an allowlist. Nothing outside it is uploaded.
