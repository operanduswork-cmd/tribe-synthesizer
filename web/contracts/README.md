# The hosted contract

What the laptop (Python) and the dashboard (`web/`) agree on. Stage 1 of the plan (D25, D26, D27), plus the brain view (D28, schema version 2). Change it here first, then on both sides, and keep `python -m strategist.test_contract` green.

| File | What it is |
|---|---|
| `strategist/hosted_schema/<kind>.schema.json` | One JSON Schema (2020-12) per hosted page kind |
| `web/fixtures/<kind>.json` | One SYNTHETIC page per kind (made-up handles `@demo_creator_a/b/c`, shortcodes `DEMO000000N`, numbers and beat names). Never real data |
| `web/contracts/job-kinds.json` | The allow-list of job kinds the site may queue and the runner may run |
| `web/contracts/brain-assets.json` | The brain view's binary assets: key format, kinds, mime, gzip, size caps, headers and layouts (Python and TS read it) |
| `web/fixtures/brain.json` | The SYNTHETIC brain page (`python -m strategist.brain_assets fixture`): real HCP codes and Yeo names, made-up values, on the tribe fixture's job and seconds |
| `web/db/migrations/0000_init.sql` | The tables (hand-checked; text + CHECK, no enums) |
| `web/db/migrations/0001_brain_assets.sql` | Schema version 2: `pages` kind `brain`, the `brain_assets` table |
| `web/db/schema.ts` | The same tables in Drizzle, for typing |
| `web/db/roles.sql` | Roles `tribe_web` and `tribe_runner`, grants, row rules on `jobs` (fresh installs, after 0000 and 0001) |
| `web/db/grants-0001.sql` | The `brain_assets` grants for a database that already has the roles |
| `strategist/contract.py` | Loads the schemas and job kinds; `validate` (`quiet=True` never repeats a page value), `check_page`, `check_job_args`, `page_key`, `layer_strings` |
| `strategist/brain_assets.py` | Builds and checks the brain page and its assets from `outputs/<job>/preds.npy` (numpy) |
| `strategist/db.py` | The runner's side of the database (psycopg 3) |
| `strategist/store.py` `locked()` | The swipe file lock the CLI and the runner share |

## Pages

Every page has `"v": 1`, and every object is closed (`additionalProperties: false`), so an extra field is a refusal, not a leak. The `pages` row is `(kind, key)`; the schema's `x-key` is the key's format, and `contract.page_key(kind, page)` returns it.

| Kind | Key | Built from | Top-level fields |
|---|---|---|---|
| `board` | `index` | `render.board_reel`, `render_board` | `v rendered stamp sorts default_sort options reels creators` |
| `reel` | shortcode | `render_reel`, `build_reel_card` (`R.build_card`, `R.counts_strip`) | `v rendered shortcode owner url posted card discount recreate beats beats_empty tribe stamps facts local_cmd` |
| `patterns` | `index` | `render_patterns`, `contrast_text` | `v rendered stamp since notes lead population tabs patterns` |
| `lab` | draft id | `render_lab`, `check_badge` | `v rendered id slug kind status title updated checked stale est_s target_s length_text badges beats variants patterns proof issues hits commands` |
| `tribe` | job id | `outputs/<job>/report.json` | `v job_id shortcode run_date framing scale clip_s time_s lines peaks flat_stretches warnings peak_image` |
| `brain` | job id | `outputs/<job>/preds.npy` + `scoring/masks/atlas-v1.json` (`strategist/brain_assets.py`) | `v job_id shortcode framing masks_version precision time_s scale frames mesh atlas areas` |
| `meta` | `index` | store counts, as-of dates | `v rendered_at layers n patterns_built_at` |
| `spend` | `YYYY-MM` | `backend/ledger.py`, Apify usage | `v month modal_usd modal_cap_usd apify_usd apify_cap_usd as_of` |

**Layers.** Every string the site shows carries `"x-layer"`: `counts`, `facts`, `shape`, `brain` or `ui`. The web sets `data-layer` from it. A string without `x-layer` is a key (it has a pattern, enum or const) and is used by code only. `contract.layer_strings(page, schema)` returns `(path, layer, text)` for every shown string, so the D20 wall check can run on real pages: no `counts` text names the brain layer, and no `brain` text names counts. Card lines get their layer from their tag (HOOK shape, HIGH/FLAT brain, BEATS shape, PACE facts, TRY ui).

**Never in a page** (the schemas have no field for them, and every display string refuses this pattern): transcripts, captions, word lists, word hits, segments, stills, HIGH quotes (`said: "`), copy-check shared runs and their sources, laptop paths (`C:/`, `\`, `/Users/`, `OneDrive`, `AppData`), `private/`, `.env`, `.npy`, `.json`, `.jsonl`, `.txt`, `.jpg` and media file names. TRIBE pages hold `display_z` lines, peaks `{t, driving_lines, edge}`, flat stretches `{start, end, driving_lines, edge}`, the scale label and the framing only: no peak values, no words.

**Brain pages (D28).** One per linked TRIBE job that has `preds.npy` on the laptop, keyed and named like its tribe page (same job, reel and `time_s`; nothing spans two jobs, D21). Fields:
- `scale` `{mode: "within-reel", label: "one colour scale for this whole reel", vmax, percentile: 99, pooled, levels: 127, colormap: "PuOr_r", grey_below: 0.15, full_at: 0.5, clipped_share}`: ONE scale for the whole reel (vmax = p99 of |model output| over every cortex vertex and every second). The frames are raw model output around the model's zero, so the legend never says "vs this reel's average". No per-row scale.
- `frames`, `mesh`, `atlas` each `{key, sha256, bytes}`: the `brain_assets` row's key, the sha256 of its stored gzip bytes (its `hash`) and its decompressed length (`raw_bytes`). `atlas` also holds `version` (`atlas-v1`), `hcp {name, labels[180], network[180], line[180], n_left[180], n_right[180]}` (HCP-MMP1 short codes in Glasser order; network = the majority Yeo-7 network; line = the masks-v1 line or null), `yeo {name, labels[7]}` (atlas names verbatim, "Yeo network 5: Limbic") and `order[180]` (indices into `hcp.labels`: Yeo network, then Glasser index).
- `areas {hcp_left[180][T], hcp_right[180][T], yeo[7][T], lines {seeing, hearing, language, attention}[T]}`: signed means of the model output over each area's vertices per second, 4 dp, unsmoothed (the tribe page's lines are smoothed). Rows follow `hcp.labels`; show them in `order`, never sorted by a value, no top-N. Per-area within-reel z exists only in the web's CSV, never as a colour.
- Atlas names mark places on the cortex, not feelings or functions: HCP codes only (no glosses), Yeo names as written, with that hint. Every label is in the schema's enum; the 180 codes and 7 names pass the rule checks.
- The CSV ("Raw numbers") is built by the web route from this page; no CSV is stored. Per-vertex floats and `preds.npy` stay on the laptop (`python -m strategist.brain_assets vertices <job> --out DIR`, refused under `web/`).

**For the projection (`strategist/hosted.py`), the differences from the render page dicts:**
- Dropped (the web has its own routes and copy in `web/copy/en.json`): `href`s, `board_href`, `nav`, `header`, static `about` lists, `levels`, `lead_note`, `completeness` (patterns page level), `hook_pair`, the board's `fetch` rows (money goes on `spend`).
- Board: `peer.caption` becomes `peer.label`; the `tribe` text is dropped (only `cells.tribe` yes/no and `filter.tribe`).
- Reel: `lanes` becomes `tribe` `{job_id, run_date, missing}`; `transcript` and `stills` are dropped; card lines lose `still`; HIGH keeps no quote; `about.stamps` becomes `stamps` `{counts, shape, brain, page}` (one per layer, never joined); `about.facts` rows become `{label, value}` with the source tails removed; `local_cmd` is `python -m strategist.render reel <sc> --open`.
- Patterns: a source's `href` becomes `url` (the public Instagram link or null) plus `in_swipe`; `use_links[].href` becomes `known`.
- Lab: `status` stays a sentence and `kind` is `draft` or `example`; `variants[].pattern_href` becomes `pattern_id`; `patterns[].href` becomes `known`; `proof[]` loses its source; copy-check `hits[]` become `{kind, where, span: [start, end] | null, count}`: where the shared run sat in his draft, never the run. A copy hit whose run is still in the draft (a span that isn't null) refuses the push, and so does any 6-word run from the copy check's corpus (swipe and ECC, `hosted.private_runs()`), so in practice a hosted copy hit is a stale one with `span: null` (D25: copy-check shared runs stay on the laptop).
- Validate with `contract.check_page(kind, page)` before `db.upsert_page`.

## Job kinds

`job-kinds.json` lists each kind with `stage`, `enabled` (true only for stage-1 free kinds), `paid`, `estimate_usd`, `billing`, a one-line `label` and an `args` JSON Schema that stands alone (shared shapes are inlined from `defs`; the test checks they match). Instagram only: a reel is always a shortcode and the runner builds the URL itself.

| Kind | Stage | Enabled | Paid | Estimate | Args |
|---|---|---|---|---|---|
| `reel.accept` | 1 | yes | no | $0 | `sc`, `field` (`hook_shape`, `format`, `cta`, `beats`, `beats.<n>` or `all`) |
| `reel.reject` | 1 | yes | no | $0 | `sc`, `field` (no `all`) |
| `reel.discount` | 1 | yes | no | $0 | `sc`, `reason` (1 to 200 chars, one line, no control chars) |
| `patterns.build` | 1 | yes | no | $0 | none |
| `lab.check` | 1 | yes | no | $0 | `draft_id` |
| `sync.push` | 1 | yes | no | $0 | none |
| `coach.new_draft` | 2 | no | no (Claude plan) | $0 | `slug`, optional `from_sc`, `pattern_id`, `brief` (500) |
| `coach.this_but` | 2 | no | no (Claude plan) | $0 | `draft_id`, optional `variant_id`, `text` (500) |
| `coach.replace` | 2 | no | no (Claude plan) | $0 | `draft_id`, `replace` (500), `with` (500) |
| `coach.tag_shapes` | 2 | no | no (Claude plan) | $0 | `sc` |
| `reel.add_link` | 2 | no | yes (Apify) | $0.003 | `sc` |
| `reel.add_handle` | 2 | no | yes (Apify) | $0.081 | `handle` (store `check_handle` rules, one leading @) |
| `tribe.lanes` | 3 | no | yes (Modal) | $0.10 | `sc` |

Shortcodes are `^[A-Za-z0-9_-]{5,20}$`, draft ids and slugs follow `strategist/lab.py`, and no argument is ever wider than what the store accepts. Coach text is data for the coach, never a command. `limits` (one paid job running, $1 and 10 paid jobs a day, 4 deep reads a month, a confirm expires after 30 min, the Modal $30 and Apify $4.50 caps) are enforced by the runner; the site only shows them.

## Database

Postgres (Neon). A fresh install applies `migrations/0000_init.sql` and `0001_brain_assets.sql` as the owner, then `roles.sql`, then sets both passwords by hand (the roles start with `PASSWORD NULL`, so nothing can log in with a committed value). The live database (roles already in) takes `0001_brain_assets.sql` then `grants-0001.sql`. Migrations are files only: never `drizzle-kit push`, and the next change is a hand-written `0002_*.sql` plus a journal entry (statements split by `--> statement-breakpoint` for the Neon HTTP driver). `schema_meta.version` is 2 (0000 sets 1, 0001 sets 2); the runner (`db.EXPECTED_SCHEMA`) refuses any other, so the deploy order is: migrate, grants, runner, web.

| Table | Columns | Notes |
|---|---|---|
| `schema_meta` | `id` (always 1), `version` | one row |
| `pages` | `kind, key, v, json, hash, updated_at` | pk `(kind, key)`; kind CHECK; json is an object; hash is sha256 of the canonical JSON |
| `images` | `key, mime, bytes, hash, updated_at` | `image/png` only, 8 B to 1 MB (`tribe/<job>/peak.png`) |
| `brain_assets` | `key, kind, mime, encoding, bytes, raw_bytes, hash, updated_at` | gzip binaries (`brain-assets.json`): `tribe/<job>/frames.i8` (TBF1, int8 [rows][20484]), `shared/fsaverage5-inflated-v1.bin` (TBM1), `shared/atlas-v1.bin` (TBA1); key and kind CHECKs agree; `application/octet-stream`, `encoding` gzip, 18 B to 2 MiB stored, 16 B to 4 MiB unpacked; hash = sha256 of the stored bytes |
| `jobs` | `id, kind, args, estimate_usd, idem_key, created_at, confirmed_at, cancel_requested, status, lease_until, started_at, finished_at, result, error_code, refusal` | kind and status CHECK; `idem_key` unique while queued or running; one running paid job at a time (partial unique index); running needs a lease; closed needs `finished_at` |
| `job_events` | `id, job_id, at, line` | fixed lines only (`db.EVENT_LINES`), 1 to 300 chars |
| `settings` | `key, value, updated_at` | `paused` (false) |

Status: `queued`, `running`, `done`, `failed`, `interrupted`, `refused`, `cancelled`.

- **`tribe_web`** (Vercel, the only secret there): SELECT on every table (`brain_assets` included, never a write); INSERT on `jobs (kind, args, estimate_usd, idem_key, confirmed_at)`; UPDATE on `jobs (confirmed_at, cancel_requested)` for queued or running rows only; the Pause switch through `SELECT set_paused(true|false)`. A free job is inserted with `confirmed_at = now()`; a paid one must be inserted unconfirmed (the insert policy refuses anything else), shows its estimate, and his confirm click sets `confirmed_at` (D26). The `jobs_web_guard` trigger lets `tribe_web` set `confirmed_at` only once, on a queued and uncancelled job, in a later transaction than the insert, and stamps it with the database's `now()` whatever value was sent; `cancel_requested` only goes from false to true. The runner also refuses a paid job whose confirm is dated ahead of its clock (2 min skew allowed) or is not later than `created_at` (`confirm_bad_time`). `numeric` comes back as a string. If you validate pages with ajv in strict mode, register the `x-layer`, `x-kind` and `x-key` keywords.
- **`tribe_runner`** (laptop): all DML. `strategist/db.py`: `load_env()` then `connect()` (autocommit, schema checked, the URL never printed); `claim_next` (oldest confirmed, uncancelled queued job, `FOR UPDATE SKIP LOCKED`, none while paused, no second paid job), `heartbeat` (renews the 90 s lease, says if he cancelled), `finish`, `interrupt_stale`, `cancel_queued`, `add_event`, `upsert_page`, `delete_missing`, `upsert_image`, `settings_get`, `is_paused`, and for the brain view `brain_asset_hashes`, `upsert_brain_asset` (key, kind, mime and caps from `brain-assets.json`, gzip magic, sha256), `delete_missing_brain_assets`, `list_brain_assets`. `strategist/sync.py push` upserts brain pages with the other pages and then only the assets whose hash changed, in one transaction, and removes the ones no brain page uses; a linked job with `preds.npy` while the atlas or the mesh is missing refuses the whole push. `sync audit` gunzips, re-hashes and structure-checks every asset. The runner still checks expiry, the re-estimate, the daily and monthly limits and the caps before it starts a claimed job, and refuses with `finish(..., "refused", refusal=...)`.

## The swipe lock

`store.locked()` holds `swipe/.lock` (msvcrt on Windows, fcntl elsewhere), is re-entrant inside one process, and raises `store.LockTimeout` (a `StoreError`) after 30 s. `save_reel`, `save_creator` and the patterns write already take it. A load-change-save is only safe when the caller holds it around the whole step: the runner wraps each job in `with store.locked():`. The CLI commands in `strategist/reel.py`, `patterns.py` and `lab.py` don't yet hold it around their whole command (left for the runner step).
