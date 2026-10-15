# Credits

This file covers what this project borrows and how it borrows it. Written 8 Oct 2026. Section 6 (the reel strategist, built 8 Oct 2026) was written 9 Oct 2026. Sections 4, 5 and 7 were updated 9 Oct 2026 for the brain view on the dashboard . Sections 1, 4 and 7 were updated 10 Oct 2026 for the shorter text on the dashboard .

**Short version:** we run Meta's TRIBE v2 model and Llama 3.2 3B unchanged. We use three brain atlases as data. Everything else was taken as ideas and parameter values (thresholds, window sizes, parcel lists), and we wrote our own code for all of it. We copied no third-party code, with one exception: a small piece of Meta's own `tribev2` code that we re-wrote. See "The one code exception" below.

**How this was checked:** we searched `scoring/`, `dashboard/` and `backend/` for each source's name and for copyright, licence and SPDX headers. The only hits were our own comments crediting a source, plus the `get_hcp_labels` exception below.

**Licence status labels used below:**
- **verified**: someone read the licence text itself (date given).
- **per research**: the licence is recorded in the upstream copy (through `docs/BUILDING-BLOCKS.md` or `docs/LICENCE.md` section 9). Nobody re-read it at the repo.
- **unverified**: not stated, unknown, or the records disagree.
- **per package metadata**: read from an installed package's metadata or a model card's licence field. Nobody read the licence text itself.

Repo names are quoted exactly as their authors wrote them.

---

## 1. The model and the language model

### TRIBE v2 (Meta FAIR)
- **What we use:** the released weights and code, unchanged.
  - Weights: `facebook/tribev2` at Hugging Face revision `f894e783020944dcd96e5568550afe2aa9743f9f`.
  - Code: `facebookresearch/tribev2` at commit `af58661791a351a448a489042a28f6c37e1c14b7`.
  - Both are pinned in `backend/tribe_app.py`. The code is pip-installed from git and imported at run time (`tribev2.demo_utils`). We don't keep a copy of it and don't patch it.
  - WhisperX is pinned through a `uvx` shim around the tool. That shim is ours.
- **Licence:** CC BY-NC 4.0, non-commercial. **Verified** 7 Oct 2026: the GitHub and Hugging Face LICENSE files are byte-identical (`docs/LICENCE.md` section 2).
- **Paper:** d'Ascoli, Rapin, Benchetrit, Brooks, Begany, Raugel, Banville, King. "A foundation model of vision, audition, and language for in-silico neuroscience". arXiv 2605.04326, 2026 (`docs/TRIBE-FACTS.md`). Cite it as the model card asks.
- **Links:** https://github.com/facebookresearch/tribev2 , https://huggingface.co/facebook/tribev2 , https://creativecommons.org/licenses/by-nc/4.0/
- **Our route :** free, credited to Meta, no upsell, never a lead magnet. This project is not made, endorsed or supported by Meta.

### Llama 3.2 3B (Meta)
- **What we use:** `meta-llama/Llama-3.2-3B`, downloaded only through official gated access into the private Modal volume. We use no mirror. It feeds TRIBE's text path, and we don't fine-tune it.
- **Licence:** Llama 3.2 Community License plus its Acceptable Use Policy. **Verified** 7 Oct 2026 against the official texts (`docs/LICENCE.md` section 8).
- **Required credit:** "Built with Llama", shown prominently.
- **Notice line:** "Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved."
- **To do before anything goes public:** put a copy of the licence at `LICENSES/LLAMA_3.2_LICENSE.txt`, as `docs/LICENCE.md` sections 12C and 12D expect. The saved text is at the upstream copy, and it hasn't been copied here yet.

### Other models TRIBE loads (unchanged)
- **Models:** V-JEPA 2 (video), Wav2Vec-BERT (audio), WhisperX 3.8.6 with faster-whisper large-v3 (word timing).
- **Licence:** **unverified**. `docs/LICENCE.md` section 2 lists these as not researched. Check them before anything goes public.

### Notice texts in use (from `docs/LICENCE.md` section 12)
- **Report page footer** (`dashboard/template.html`): the 12E text.
  - Text: "Predicted average-brain response from TRIBE v2 (Meta FAIR, CC BY-NC 4.0). Built with Llama. Non-commercial use only. Not a view forecast."
  - The footer also carries the Llama notice line and "not made, endorsed or supported by Meta".
- **Web page footer** (12A), for the later public site: "Built on TRIBE v2 by Meta FAIR, licensed CC BY-NC 4.0 (non-commercial). Built with Llama. Free, not affiliated with Meta. Shows a predicted average-brain response, not a view forecast."
- **Private dashboard footer (10 Oct 2026):** one short line, "TRIBE v2 · Meta FAIR · CC BY-NC 4.0 · Built with Llama", with an (i) on every page that opens to the full 12A text, word for word (`docs/LICENCE.md` 12A note). Private site only; anything public shows the full 12A text.
- **Llama link:** "Built with Llama" on the report page links to the Llama 3.2 licence (https://www.llama.com/llama3_2/license/), as section 12A asks. Fixed 8 Oct 2026; it used to point at the Hugging Face model page. Once `LICENSES/LLAMA_3.2_LICENSE.txt` exists, the public site can link to that copy instead.

---

## 2. The one code exception

**`scoring/build_masks.py`, `hcp_labels_one_hemi` / `get_hcp_labels_both`**

- **What it is:** a nibabel re-write of `tribev2.utils.get_hcp_labels(mesh="fsaverage5", combine=False, hemi="both")` at commit `af58661...`.
  - It repeats upstream's label clean-up: drop the first 2 characters, remove `_ROI`, remove `-lh`/`-rh`, keep vertices below 10,242, and add 10,242 on the right side.
  - The code comments call it "a copy". With `--verify-mne`, the script also runs the upstream mne code path and checks that both give the same dict.
- **Licence:** treat it as derived from `tribev2` code, under **CC BY-NC 4.0**. These are the same terms as the model, so nothing new limits us, but keep this credit and keep it non-commercial.

---

## 3. Ideas and parameter choices (no code copied)

| Source | What we took | Where it lives in our code | Licence of their code |
|---|---|---|---|
| **techfreakworm/tribev2-brain-timeline** (https://github.com/techfreakworm/tribev2-brain-timeline, `src/tribescore/metrics.py`) | **Method:** each line is the mean over a parcel set's vertices per second, then a Gaussian smooth with sigma 2 s and truncate 3. **Parcel lists:** the HCP-MMP1 sets behind our seeing, hearing, language and attention lines, with our changes from `docs/SCORING.md` 9.1. **Other:** the "under about 10 s comes out flat" warning, and "only relative temporal dynamics are valid". **Our differences:** we smooth first and then standardise to z (they standardise first). We put A5 in language only. We dropped the DLPFC parcels and PGi/PGs from attention. **Not taken:** their vmPFC/OFC proxy curve. | `scoring/score.py` (`SIGMA_S`, `TRUNCATE`, `SHORT_CLIP_S`), `scoring/build_masks.py` (`LINES`) | Apache-2.0 with a NOTICE, **per research**. We copied no files, so their NOTICE does not need to travel. Copy it into `LICENSES/` if code is ever copied. |
| **exhuman777/tribe-v2-engagement-analysis** (https://github.com/exhuman777/tribe-v2-engagement-analysis) | **Thresholds:** z of +1 for a peak, and z of -1 or lower for 4 s or more for a flat stretch. **Driving lines:** the idea of saying which networks rose or fell. **Yeo-7:** loading the `Yeo2011_7Networks_N1000` annots and dropping the medial wall, used for the cross-check. **Later:** the skill shape for `/brainscore`. **Not taken:** their hand-signed combined formula. | `scoring/score.py` (`PEAK_Z`, `FLAT_Z`, `FLAT_MIN_S`, `DRIVE_Z`), `scoring/build_masks.py` (Yeo-7 cross-check) | MIT, **per research** |
| **JoshW-dev/tribev2-test** (https://github.com/JoshW-dev/tribev2-test, `PEAK_FIX_INSTRUCTIONS.md`) | **The fix for peaks bunching at the end of a clip:** detrend, standardise to z, mark the edges and keep a minimum spacing between peaks. **Not taken:** their hand-weighted index. | `scoring/score.py` (`shape_z` detrend, edge seconds, peak spacing) | Not stated, **unverified**. Ideas only. |
| **MoburstAI/tribe-v2-analyzer** (Hugging Face Space, https://huggingface.co/spaces/MoburstAI/tribe-v2-analyzer) | **Last-2 s rule:** no peaks in the last 2 s, because those rows are artefacts. **Later:** their curve-shape labels. **Not taken:** their 1 to 10 rating or their weights. Affiliation with the agency Moburst is not confirmed. | `scoring/score.py` (`EDGE_S`, last-2-s exclusion) | No licence declared, **unverified**. Ideas only. |
| **Sahu & Pandey, arXiv 2607.01400** (https://arxiv.org/abs/2607.01400; code https://github.com/mercurialsolo/tribe-replay-heatmaps). Full title not recorded in our research. | **RMS line:** root-mean-square over all 20,484 vertices per second ("global field power"), kept as a calibration-only line. **Spacing:** greedy peak picking, at least 4 s apart. **Later:** position-controlled partial correlation and a loudness baseline (`docs/VALIDATION.md`). | `scoring/score.py` (`calibration_only.overall_rms`, `PEAK_SPACING_S`) | Code licence **unverified**. `docs/ARCHITECTURE.md` says MIT, but `docs/BUILDING-BLOCKS.md` B5 says not stated. Paper licence not checked. |
| **Reeled In** (sxnnywu/reeled-in, https://github.com/sxnnywu/reeled-in, Devpost https://devpost.com/software/loopy-9ev74g) | **Shared scale:** never scale each clip to its own 0 to 1 range. Use one shared scale per comparison (their fix used a 95th-percentile reference). **Destrieux grouping:** transverse temporal plus planum temporale for the hearing cross-check. **Not taken:** their hand weights, or their swap to an ungated Llama mirror. | `report.json` `scale` and `lines[*].shared` (null until a reference of your reels exists); the A-vs-B panel later; `scoring/build_masks.py` (Destrieux auditory mask) | Not addressed, **unverified**. Ideas only. |
| **DataCamp TRIBE v2 tutorial** (Aashi Dutt, https://www.datacamp.com/tutorial/tribe-v2-tutorial) | **Later (A-vs-B panel):** the difference method, `preds_a[t] - preds_b[t]` per vertex plus the per-second L2 norm of the difference. **Now:** clipping the brain picture at the 99th percentile of absolute values. **Facts used:** 1 row per second and the left-then-right vertex order. **Inputs:** the caution that short inputs give low, flat output. **Not taken:** its numpy pin. | `scoring/score.py` (`BRAIN_PERCENTILE`), `backend/tribe_app.py` (`WARN_SECONDS`); difference maps not built yet | A tutorial, not code we import. Terms not checked. |
| **video-performance-analyzer (vpa)** (christopher-inegbedion, https://github.com/christopher-inegbedion/video-performance-analyzer) | **Word timing:** use the Word rows TRIBE itself used (they write their own timings into TRIBE's cache so the two match), rather than transcribing separately. **Black frames:** leave cuts to black out of peak finding. **Later:** refuse to call correlations findings below a minimum number of labelled reels (our bar is 20 to 30). | `scoring/score.py` (words come from `events.json`; black seconds skipped for peaks), `backend/tribe_app.py` (writes `events.json`) | MIT wrapper, **per research**. TRIBE terms apply separately. |

### Dashboard ideas (the report page, panels 1 to 5)

The page in `dashboard/template.html` and `dashboard/render.py` is our own code. The sources below gave ideas only, as listed in the dashboard plan. **No code was copied from any of them.** We searched `dashboard/` and `scoring/` for each name and found nothing.

| Source | Idea we took | Where it shows up | Licence of their work |
|---|---|---|---|
| **Meta's own `tribev2` Colab demo notebook** (`tribe_demo.ipynb`, linked from https://huggingface.co/facebook/tribev2) | Video frame, transcript words and brain response on one shared time axis. | Panel 4: the word strip under the lanes, on the same time axis | CC BY-NC 4.0, same as TRIBE v2. Credited here and in the page footer. |
| **jakebeau_** (viewer demo, https://www.youtube.com/watch?v=yYa2d8e8ppE ; https://www.tiktok.com/@jakebeau_/video/7622479702321630495) | A player that plays the video next to the predicted response over time, to find moments while editing. | Panel 2: the synced player and playhead | No code released (the upstream copy). Ideas only. |
| **vanjaoljaca/tribev2-video-worker** (https://github.com/vanjaoljaca/tribev2-video-worker, `scripts/synced_video_activation.py`) | Syncing the video's time with the per-second response rows. | Panel 2: the playhead and click-to-jump | MIT, **per research**. Not copied: none of its code is in this repo. Whether the file was read during the build is not recorded. **Not taken:** its "rough cortical sections" made from vertex-index slices, which are not brain regions (`docs/SCORING.md` section 4). |
| **anasmk9/tribe-v2-neuromarketing** (Hugging Face Space, https://huggingface.co/spaces/anasmk9/tribe-v2-neuromarketing) | A frame gallery: still frames shown next to the moments. | Panel 5: frame thumbnails at peaks and flat stretches (made with ffmpeg by `render.py`) | CC BY-NC 4.0, **per research**. Ideas only. **Not taken:** its weighted "cognitive clusters" or their rescaling into a rating. |
| **recozers** (https://github.com/recozers/tribe-inference) and **tribev2 PR #80** (`PlotBrainNilearn`) | Drawing the brain picture headless, on a machine with no screen. | Panel 5: the brain picture popup (`peak.png`, drawn by our own pure-matplotlib code in the scoring script, `render_brain`) | recozers: **unverified**. PR #80: its web UI "inherits CC BY-NC 4.0" (`docs/LICENCE.md` section 2). Ideas only. |
| **theisaacmed/Greenlight** (https://huggingface.co/spaces/theisaacmed/greenlight-tribe) | Its demo-only stance: the feature stays out of anything paid. | Panel 1: the free, non-commercial framing and footer | "Research, academic demos, and internal evaluation only", **per research**. Ideas only. |
| **rippere/tribe-social** (https://github.com/rippere/tribe-social) | The wording of its NOTICE: say plainly that commercial use of TRIBE output is not allowed. | Panel 1: the footer ("Non-commercial use only") | Apache-2.0 with a NOTICE, **per research**. No files copied, so the NOTICE does not need to travel. |

**Also cited in `docs/SCORING.md` as agreeing on a choice.** Nothing was taken from these sources alone:
- **Varnan-Tech:** the +/-1 z thresholds. Licence not stated.
- **theisaacmed/Greenlight:** peaks about 4 s apart, and the 0-3 s hook window. Its licence says "research, academic demos, and internal evaluation only".
- **rippere/tribe-social:** the 0-3 s hook window. Apache-2.0 per research.
- **Ochakov64:** the 0-3 s hook window. Licence not recorded.

---

## 4. Brain atlases and mesh (data, read only)

The sources were recorded by the masks build, and their sha256 hashes are in `scoring/masks/masks-v1.json`. We read these files as data and never run anything from them.

**Since 9 Oct 2026 ** they also feed the brain view on the dashboard. `scoring/build_atlas.py` writes `scoring/masks/atlas-v1.json` (the 180 HCP codes, each area's Yeo network, and a lookup of which area and network each surface point belongs to). `strategist/brain_assets.py` packs the lookups and the mesh for the private database. It is still data only, and it stays behind his login.

### HCP-MMP1.0 (Glasser), projected on fsaverage
- **Files:**
  - left: https://ndownloader.figshare.com/files/5528816
  - right: https://ndownloader.figshare.com/files/5528819
  - fetched with `mne.datasets.fetch_hcp_mmp_parcellation(accept=True, combine=False)`.
  - Dataset page: https://figshare.com/articles/dataset/HCP-MMP1_0_projected_on_fsaverage/3498446
- **Dataset citation:** Mills, Kathryn (2016). HCP-MMP1.0 projected on fsaverage. figshare. Dataset. https://doi.org/10.6084/m9.figshare.3498446.v2
- **Paper:** Glasser MF, Coalson TS, Robinson EC, Hacker CD, Harwell J, Yacoub E, Ugurbil K, Andersson J, Beckmann CF, Jenkinson M, Smith SM, Van Essen DC. A multi-modal parcellation of human cerebral cortex. Nature 536(7615):171-178, 2016. doi:10.1038/nature18933
- **Licence:**
  - The annot files are CC BY 4.0, according to the figshare metadata.
  - The parcellation falls under the WU-Minn HCP Consortium Open Access Data Use Terms (https://balsa.wustl.edu/WN56; mne prints the same text).
  - Clause 4: derived data may be redistributed only under these same terms. **Our line masks in `scoring/masks/masks-v1.json` are derived data**, so they carry these terms if they are ever shared.
- **Acknowledgement required in public presentations (clause 5.1):** "Data were provided [in part] by the Human Connectome Project, WU-Minn Consortium (Principal Investigators: David Van Essen and Kamil Ugurbil; 1U54MH091657) funded by the 16 NIH Institutes and Centers that support the NIH Blueprint for Neuroscience Research; and by the McDonnell Center for Systems Neuroscience at Washington University."
- **Derived data on the dashboard (9 Oct 2026):** the per-point area lookups (`atlas-v1.json` and `shared/atlas-v1.bin`), the per-area means in each reel's brain page, and the numbers file (CSV) built from them are derived data under clause 4. They stay behind his login and are never shared, except under these same terms. Areas show by their short HCP code only.
- **Where the clause 5.1 acknowledgement is shown :** the brain view footer, the Areas tab and the numbers file header. The numbers file also says "derived data shared only under the HCP Open Access terms".
  - **Since 10 Oct 2026 , on the dashboard:** the acknowledgement and the atlas credits sit behind an (i) in the brain view and the Areas tab, one tap away and word for word. The numbers file (CSV) header still carries the acknowledgement in full. The offline pages have never carried it; that is fine while they stay private, and section 7 applies before anything public.
- **Display text, word for word** (the terms' optional "[in part]" filled in as "in part"; `web/copy/en.json` must match it exactly): "Data were provided in part by the Human Connectome Project, WU-Minn Consortium (Principal Investigators: David Van Essen and Kamil Ugurbil; 1U54MH091657) funded by the 16 NIH Institutes and Centers that support the NIH Blueprint for Neuroscience Research; and by the McDonnell Center for Systems Neuroscience at Washington University."

### Yeo-7 networks (Yeo2011, 7 networks, N1000, fsaverage5)
- **Files:** `lh/rh.Yeo2011_7Networks_N1000.annot` (and the split_components versions) from https://github.com/ThomasYeoLab/CBIG at commit `634f676630929a71297852d01dd92a287103e861`. Network names come from `7NetworksOrderedNames.csv` in the same repo.
- **Paper:** Yeo BT, Krienen FM, Sepulcre J, Sabuncu MR, Lashkari D, Hollinshead M, Roffman JL, Smoller JW, Zollei L., Polimeni JR, Fischl B, Liu H, Buckner RL. The organization of the human cerebral cortex estimated by intrinsic functional connectivity. Journal of Neurophysiology 106(3):1125-1165, 2011. doi:10.1152/jn.00338.2011
- **Licence:** the repo's LICENSE.md is MIT, "Copyright (c) 2016 Computational Brain Imaging Group (CBIG)". No separate data licence was found, so the data terms are **unverified**.
- **Used for:** the cross-check (seeing vs Yeo Visual; attention vs Yeo Dorsal plus Ventral Attention).
- **Since 9 Oct 2026 , also:** the network breakdown on the dashboard. Network names are shown verbatim from `7NetworksOrderedNames.csv` (for example "Yeo network 5: Limbic", with the hint that atlas names mark places on the cortex, not feelings), and each HCP area is grouped under the Yeo network that holds most of its points. The paper above is cited in the brain view credits and the numbers file header.

### Destrieux 2009 (aparc.a2009s), fsaverage5
- **Files:**
  - left: https://www.nitrc.org/frs/download.php/9343/lh.aparc.a2009s.annot
  - right: https://www.nitrc.org/frs/download.php/9342/rh.aparc.a2009s.annot
  - fetched with `nilearn.datasets.fetch_atlas_surf_destrieux`.
- **Paper:** Destrieux C, Fischl B, Dale A, Halgren E. Automatic parcellation of human cortical gyri and sulci using standard anatomical nomenclature. NeuroImage 53(1):1-15, 2010. doi:10.1016/j.neuroimage.2010.06.010
- **Licence:** **unverified**. The nilearn dataset description says "License: unknown".
- **Used for:** the cross-check only (hearing vs Destrieux auditory). It is not used by the brain view .

### fsaverage5 mesh (inflated surface and sulcal depth)
- **Source:** FreeSurfer's fsaverage5, as bundled with nilearn (`nilearn.datasets.fetch_surf_fsaverage('fsaverage5')`). Our copy is `scoring/masks/fsaverage5-mesh.npz`, which draws the brain picture.
- **Licence:** **unverified**. The nilearn dataset description says "License: unknown".
- **Since 9 Oct 2026 :** the inflated surface and sulcal depth are also stored in the private database (`shared/fsaverage5-inflated-v1.bin`, about 0.5 MB) and drawn by the 3D brain view, behind his login. They never go in `web/` or `web/public`; the web's test fixtures use a made-up sphere instead. **Check the FreeSurfer licence for fsaverage5 before anything public.** Until then the mesh stays private.

---

## 5. Tools we run but don't copy

- **Build time only:** mne, nibabel and nilearn read the atlas files.
- **Run time:** numpy, scipy (`gaussian_filter1d`) and matplotlib, plus ffmpeg for the frame thumbnails.
- **Licences:** **unverified** here. They are standard open-source packages, used as installed and not bundled.

### The 3D brain view on the dashboard (`web/`, added 9 Oct 2026)
- **three.js** 0.186.1 (npm `three`, pinned): MIT, "Copyright © 2010-2026 three.js authors". **per package metadata** (the `license` field and the LICENSE file in `web/node_modules/three`, 9 Oct 2026).
- **How it is used:** installed with npm and bundled, unchanged, into the brain view's lazy-loaded script by the build. None of its code is copied into our source. `@types/three` 0.186.0 is a build-time type package only.
- **Notice:** the production build drops three.js's `@license` comment from the bundled script, so its MIT notice must ship with the site before anything public (the NOTICE file in section 7).

---

## 6. The reel strategist (`strategist/`, added 8 Oct 2026)

**How this was checked (9 Oct 2026):**
- **Code:** we searched `strategist/` for copyright, licence and SPDX headers. The only hits were the Llama notice line in the page footers.
- **No third-party code is copied.** Package and model licences were read from the installed package metadata and the Hugging Face API, not from the licence files themselves. They are labelled **per package metadata** below.

### Local transcription (installed with pip, run as installed, not bundled)

| Package or model | Version | Licence | Status |
|---|---|---|---|
| faster-whisper (SYSTRAN) | 1.2.1 | MIT | per package metadata |
| ctranslate2 (OpenNMT) | 4.7.1 | MIT | per package metadata |
| av (PyAV, audio decoding for faster-whisper) | 17.0.1 | BSD-3-Clause | per package metadata |
| onnxruntime (a faster-whisper dependency. We don't switch on its voice-activity filter) | 1.25.0 | MIT | per package metadata |
| tokenizers (Hugging Face) | 0.22.1 | Apache-2.0 | per package metadata |
| huggingface-hub | 0.36.0 | Apache-2.0 | per package metadata |
| Model `Systran/faster-whisper-small.en` (default), plus `base.en` and `base` in the cache | n/a | MIT on the model card | per package metadata (the model card's licence field via the HF API, 9 Oct 2026) |

**About the model:**
- **What it is:** these are SYSTRAN's CTranslate2 conversions of OpenAI's Whisper models.
- **Upstream licence:** the Hugging Face card for `openai/whisper-small.en` says Apache-2.0. OpenAI's original Whisper release is MIT. Neither was re-read here.
- **How it was fetched:** downloaded once into the usual Hugging Face cache, with no token.

### Other creators' public posts (data, not code)
- **Source:** counts and captions come from Apify's `apify~instagram-scraper` (public posts, no login), fetched by you.
- **Whose they are:** the reels, captions and transcripts belong to their creators.
- **What to keep:** links, numbers and shapes only. Keep transcripts, stills and videos private and never publish them. Do not commit a swipe folder.

### Page patterns from Mobbin (ideas only)
- **Where they came from:** the 8 Oct 2026 strategist plan (the design plan, "The design") chose these patterns from read-only Mobbin sweeps.
- **What Mobbin is:** a library of screenshots of other companies' apps. Those companies own their designs.
- **What we took:** the idea behind each pattern. **No screenshots, images, assets, styles or code were copied.** Our pages are our own HTML, CSS and JS.

| Product (as seen on Mobbin) | Idea we took | Where it shows up |
|---|---|---|
| Bloom (ad library "recreate") | a Recreate button on each reel, which copies a script-lab command | `strategist/templates/board.html`, `card.html`, `patterns.html` |
| Google Ads | a Cards / Table view switch | `board.html` |
| Coda | a "counts as of, refresh manually" stamp | `board.html`, `patterns.html` |
| Maze | a summary line with its time after the claim | `card.html` |
| Descript | clickable time chips | `card.html`, `dashboard/template.html` |
| Hotjar | the fold order under the summary | `card.html`, `dashboard/template.html` |
| Profound | a "made by, when" stamp | `card.html` (About this data) |
| Productboard | counts per item, plus a NEW tag | `patterns.html` |
| Databricks | a "completeness unknown" note | `patterns.html` |
| Contractbook | "Replace X with Y" | `lab.html` |
| Canva | "This but..." refinements | `lab.html` |

**Rejected on purpose** (they break D8 or D20):
- Higgsfield's virality predictor (a 0 to 100 score and a hook score);
- Hume's emotion timelines;
- Lovable's star grades.

---

## 7. Before anything goes public

This list is in addition to the full checklist in `docs/LICENCE.md` section 13:
- Add `LICENSES/LLAMA_3.2_LICENSE.txt`, and a NOTICE file (12D) listing the entries above.
- Add the HCP clause 5.1 acknowledgement wherever the brain picture or the line masks are shown. On the dashboard it sits in the brain view footer, the Areas tab and the numbers file header (D28, display text in section 4); keep it on anything public. **Since 10 Oct 2026 :** on the dashboard it sits behind an (i) in the brain view and the Areas tab, and the numbers file keeps it in full. Anything public shows it in full, not behind an (i).
- Record the HCP-MMP1, Yeo-7 and Destrieux terms in `docs/LICENCE.md` section 2. **Done 9 Oct 2026:** section 2 used to say "not researched" and now points to section 4 here.
- **The brain view data :** check the FreeSurfer licence for the fsaverage5 mesh and the Yeo-7 data terms before the mesh, the atlas lookups or the area means appear anywhere public. Until then they stay in the private database, behind the login.
- **HCP derived data (clause 4):** the atlas lookups, the area means and each reel's numbers file are shared, if ever, only under the HCP Open Access terms.
- Re-read every licence marked **per research**, **unverified** or **per package metadata** at the source.
- The swipe pages and the swipe file never go public at all (`docs/LICENCE.md` section 6b).
- If any third-party file is ever copied, keep its notice, mark the changes and list it here.
