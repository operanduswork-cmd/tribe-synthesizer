# tribe-open

A free, educational toolkit for studying short-form video with Meta FAIR's TRIBE v2 brain-response model.

Made by Operandus. Free and non-commercial.

It does two things:

1. **Outlier board.** Collect public reels from creators you choose, compare each reel's plays to that creator's own median, and list the outliers (2x or more). It shows counts and hook shapes. It is a swipe file, not a ranking.
2. **Predicted average-brain response per reel.** Run a 10 to 60 second clip through TRIBE v2 on a Modal GPU. You get a second-by-second predicted response for four lines (seeing, hearing, language, attention), the peak moments, the word list, and a 3D brain view.

**What this is not.** It is an analysis tool, not a prediction of views, reach or virality. It shows a predicted average-brain response. That is an average brain, not your audience. There is no score and no winner.

Free and non-commercial. No sign-up, no email gate, no paid tier, no offer.

## Architecture

```
your machine                    Modal (your account)              Vercel + hosted services (optional)
-----------------------         -----------------------           ---------------------------------
strategist/  swipe file   --->  backend/tribe_app.py   GPU        web/  Next.js dashboard
  reel add / import               TRIBE v2 inference               reads pages from Neon Postgres
scoring/     masks, score  <---   saves preds, then exits          Upstash Redis: job queue / limits
dashboard/   offline pages        (no keep-warm)                   Vercel Blob: private reel videos
strategist/sync.py  ------------------------------------------>   (only schema-checked pages sync)
```

- `backend/` Modal app. Downloads weights once into a Modal volume, runs inference, writes a cost ledger and refuses to run past your monthly cap.
- `scoring/` turns raw predictions into the report: real atlases only (HCP-MMP1, Yeo-7), within-reel scale by default. See `docs/SCORING.md`.
- `strategist/` the reel swipe file, hook shapes, copy checks, hosted-page contracts and the laptop job runner.
- `dashboard/` offline HTML report pages.
- `web/` the Next.js 16 dashboard (board, reels, brain view, patterns, lab, settings).
- `docs/` scoring method, version pins and gotchas, licence notes.

## Requirements

- Python 3.11, Node 20+, Git
- Accounts you create yourself (all have free tiers): Modal, Hugging Face (approved for Llama 3.2 3B), Neon, Upstash, Vercel, Apify
- Optional: Chrome, for the Playwright tests

## Try it in demo mode (no accounts, no money)

The dashboard ships with synthetic fixtures (`web/fixtures/`: three made-up creators and demo reels). Demo mode touches no database, Redis, Modal or network service.

```
cd web
npm ci
npm run build
npm run start -- -p 3100        # open http://127.0.0.1:3100/board
npm run test:e2e                # Playwright against the fixtures, phone and laptop widths
```

`TRIBE_DATA_SOURCE` defaults to `fixtures`. `npm run dev` also works.

Python tests (no network, no GPU):

```
python -m unittest discover -s strategist -p "test_*.py" -t .
python -m unittest discover -s backend -p "test_*.py" -t .
python -m unittest discover -s dashboard -p "test_*.py" -t .
python -m unittest discover -s scoring -p "test_*.py" -t .
```

The brain mesh and atlas files are not committed. Build them with `python scoring/build_masks.py` and `python scoring/build_atlas.py` (they fetch the public atlases). Tests that need them are skipped or fail until then.

## Setup for real runs

Copy `.env.example` to `.env`, fill in your own values, and never commit it. Everything below uses placeholder names only.

### 1. Modal (GPU)

1. Create a Modal account, then `pip install modal` and `modal setup`.
2. Pick the profile to bill and set `TRIBE_MODAL_PROFILE` to its name. Check with `modal profile current`. The backend refuses to run on any other profile.
3. Request access to `meta-llama/Llama-3.2-3B` on Hugging Face through the official form. Use no mirrors.
4. Create a read token and store it as a Modal secret, used only for the one-time weight download: `modal secret create huggingface HF_TOKEN=<your token>`.
5. Set a hard monthly cap before the first deploy: `modal secret create tribe-config MONTHLY_BUDGET_CAP_USD=<number>`. Blank or 0 means every run is refused.
6. Start on the cheapest GPU that fits (A10G). Functions run inference and exit, with no keep-warm.

### 2. Neon (Postgres, for the web dashboard)

1. Create a project and three roles: web (read), runner (laptop job runner), owner (migrations).
2. Put their URLs in `TRIBE_WEB_DATABASE_URL`, `TRIBE_RUNNER_DATABASE_URL` and `TRIBE_OWNER_DATABASE_URL`.
3. Apply the migrations and grants in `web/db/` (`npm run db:migrate` with the owner URL set, then `roles.sql` and `grants-*.sql` with your own role names).

### 3. Upstash (Redis)

Create a Redis database. Set `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` (the Vercel Marketplace `KV_REST_API_*` names also work).

### 4. Vercel (dashboard hosting)

1. Create your own Vercel project from `web/`. Turn on Vercel Authentication so the dashboard stays private to you.
2. Set `TRIBE_DATA_SOURCE=db` and the web database and Redis variables in the project's environment settings.
3. For private reel videos, add a Blob store and set `BLOB_READ_WRITE_TOKEN`. Set `TRIBE_VERCEL_SCOPE` to your own team or user slug.

### 5. Apify (optional)

Only for public reels that cannot be downloaded without a login. Set `APIFY_TOKEN`. It costs well under 1 cent per reel. Paid commands print their estimate and do nothing without `--yes`.

## Run commands

```
# One clip on Modal (checks the profile first)
modal run backend/tribe_app.py --video-path clip.mp4 --label demo
# Windows launcher that checks the profile for you
.\backend\tribe.ps1 reel path\to\clip.mp4

# Score a finished output folder
python scoring/score.py outputs/<job_id>

# Swipe file
python -m strategist.reel add @handle        # prints the cost first
python -m strategist.reel list

# Offline report page
python dashboard/render.py outputs/<job_id>
```

Inputs: 10 to 60 second clips for now. Clips under about 10 s come out flat, and audio over 60 s can duplicate words (upstream bugs). Images must become short clips and are off-distribution. Version pins are in `docs/GOTCHAS.md`.

## Privacy model

- Secrets live in `.env` and Modal or Vercel secrets. They are never committed, printed or put in code. The HF token is only for downloading weights.
- `swipe/`, `drafts/`, `media/`, `outputs/`, `reports/` and `research/` are git-ignored. They hold other creators' data and your own drafts.
- Only schema-checked "hosted pages" sync to the dashboard (`strategist/hosted_schema/`). Transcripts, captions, word lists and stills stay on your machine. A leak check rejects file paths and private folders.
- Keep the dashboard behind Vercel Authentication. Do not publish other creators' posts or videos.
- Only upload clips you have the right to use.

## Licence and credit

This tool runs TRIBE v2 by Meta FAIR (d'Ascoli et al., 2026).
TRIBE v2 weights are licensed CC BY-NC 4.0 (non-commercial): https://creativecommons.org/licenses/by-nc/4.0/
Model: https://huggingface.co/facebook/tribev2 | Code: https://github.com/facebookresearch/tribev2
Cite the TRIBE v2 paper as its model card asks.

**Built with Llama.** The text path uses meta-llama/Llama-3.2-3B under the Llama 3.2 Community License. Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved. Add a copy of the licence text to `LICENSES/`.

Our own code is MIT (see `LICENSE`). **That does not change the model licence.** TRIBE v2 weights and outputs remain CC BY-NC 4.0, and the whole project is for non-commercial use only.

- Allowed: personal use, learning, research, free non-commercial use with credit.
- Not allowed: selling access or scores, paid tiers, cost recovery, client work, paid deliverables, using it to win clients.
- Commercial use needs Meta's permission (research-licensing@meta.com).

**Not affiliated with or endorsed by Meta.** This is an analysis tool, not a prediction of views. Outputs are a predicted average-brain response, not a forecast of views or virality.

Third-party code and atlases are listed in `LICENSES/CREDITS.md` and `NOTICE`. Licence notes and the texts to show are in `docs/LICENCE.md`. Run its checklist before you share anything publicly.

Footer to show wherever the tool is public:

> Built on TRIBE v2 by Meta FAIR, licensed CC BY-NC 4.0 (non-commercial). Built with Llama. Free, not affiliated with Meta. Shows a predicted average-brain response, not a view forecast.

## Notes

Comments such as "D25" or "D28" in the code point to decision numbers from the original build log, which is not included.
