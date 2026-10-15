# Scoring: turning TRIBE v2 output into useful outputs

> **Status (9 Oct 2026):** built as `scoring/score.py` (scoring version 0.1) with real masks in `scoring/masks/masks-v1.json`, run on 3 TRIBE jobs; the brain view (§14b) is being built. Written 7 Oct 2026 as a spec.
>
> **What this file is for:** the build session uses it to write the analysis step. That step takes the raw `(T, 20484)` array and produces the per-second lines, peaks, flat stretches, word hits, brain picture and A vs B compare.
>
> **Sources:** upstream code and community write-ups, named inline. Treat anything unsourced as the author's own choice.
>
> **Tags:** **[ours]** = our own design choice, not taken from a source. **[unverified]** = not checked; test it. **Every threshold in this file is a starting point to calibrate, not a fact.**
>
> **Framing rule (fixed):** everything we output is "predicted average-brain response". Never views, virality, reach, CTR or a forecast of any kind.
>
> **Relation to other docs:** `the build notes` §7 is a short summary of this step. Where the two differ, this file wins (differences listed in §17). The full calibration protocol lives in `VALIDATION.md` §5. This file only says what scoring must produce and store for it.

---

## 1. Short version

1. The model gives one row per second, 20,484 numbers per row. Cortex only, average brain. The numbers are positions on a mesh, not brain regions.
2. Never slice vertex number ranges and call them "Visual" or "Amygdala". Map vertices to a real atlas. Meta's own `tribev2.utils` gives HCP-MMP1 (Glasser) parcels.
3. Build 4 lines: **seeing, hearing, language/meaning, attention**. Each line is the mean of its parcels' vertices for each second.
4. Smooth each line over time (Gaussian, sigma 2 s).
5. Put each line on two scales:
   - **within-reel z**: only for finding peaks and flat stretches inside one reel;
   - **shared scale**: for anything compared across reels, including A vs B.
6. The output is already shifted 5 s by the model [upstream README]. Do not shift it again. Test this once.
7. Never scale each clip to its own 0-100. Never sum activation over a whole clip (it tracks length).
8. Starting rules:
   - peak = z of +1 or more, at least 4 s apart;
   - flat stretch = z of -1 or less for 4 s or more;
   - hook window = seconds 0 to 3.
9. Word hits come from the exact Word rows TRIBE used.
10. No single score. No "virality". After 20 to 30 reels, the flags get checked against real retention graphs (`VALIDATION.md` §5).

---

## 2. Why we never say views

Every careful test against real outcomes came back null or weak (Report §E):

| Test | Result | Source |
|---|---|---|
| TikTok viral vs dud, n=61 | Baseline (followers + duration) AUC 0.790. Adding TRIBE: 0.735. TRIBE alone: 0.677 | spike-tribe-validation |
| YouTube most-replayed, n=48 | Partial r +0.058 (95% CI -0.04 to 0.15, p=0.23). No better than loudness or motion | arXiv 2607.01400 |
| 24 videos, 3 creators | r = 0.25 (p = 0.24), below its own pre-set bar of 0.4 | rippere/tribe-social |
| One military Shorts channel, 190 videos | rho 0.437 inside the channel. "cross-channel transfer was not supported" | MECI-Lab |
| 15 reels, one brand | Spearman -0.62, fitted and reported on the same 15 reels | Alkimia |

So the scoring layer describes the predicted response. It never predicts performance.

---

## 3. What the model hands us

| Fact | Detail | Source |
|---|---|---|
| Call | `preds, segments = model.predict(events)` | [upstream] `demo_utils.py` |
| Shape | `preds` is `(n_kept_segments, 20484)` | [upstream] `predict()` docstring |
| Time step | One row per TR. TR is 1 s (1 Hz) | DataCamp, BERG model card (web-findings); `the build notes` §6 |
| Rows can go missing | `predict()` drops segments with no events by default (`remove_empty_segments=True`). So **use each segment's start time as the time axis**, not the row number | [upstream] `demo_utils.py` |
| Segment objects | Have `.start`, `.stop`, `.duration` and `.ns_events` | [upstream] `utils.split_segments_by_time`, `demo_utils.predict` |
| Mesh | fsaverage5. 10,242 vertices per hemisphere. Left first (0 to 10,241), then right (10,242 to 20,483) | DataCamp (Report §C.5). Confirmed by [upstream] `get_hcp_labels`, which adds 10,242 to every right-hemisphere index |
| Whose brain | The "average" subject only | [upstream] README; HF discussion #10 |
| Cortex only | No NAcc, amygdala or hippocampus. A separate `facebook/tribev2-subcortical` model exists (issue #23). Out of scope for v1 | Report §D.3 |
| Time offset | Predictions "are offset by 5 seconds in the past, in order to compensate for the hemodynamic lag" | [upstream] README line 32 |
| Units | Relative only. "absolute scores are meaningless, only relative temporal dynamics are valid" | techfreakworm (Report §D.2) |
| Repeatable | Same input gives the same output ("Predictions are deterministic") | arXiv 2609.15685 (web-findings) |
| Short clips | Under about 10 s gives flat timelines (techfreakworm). DataCamp says inputs under 15 to 30 s give low, flat activation | web-findings |
| Word rows | `type` = "Word", with `text`, `start`, `duration`, `sentence`, `sequence_id`, `language`. Start times are already in clip seconds | [upstream] `eventstransforms.ExtractWordsFromAudio` |
| Transcription language | Hard-coded to `"english"` by default | [upstream] `ExtractWordsFromAudio.language` |
| Chunking | Audio and video are cut into chunks of 30 to 60 s before prediction | [upstream] `get_audio_and_text_events` |

`the build notes` §5 and §6 mark `segments` and the offset as unverified. The upstream read above settles the README wording and the segment fields. The one-time test in §7 still checks the offset in practice.

---

## 4. Why vertex number ranges are NOT brain regions

### The two reasons

1. **Hemisphere order.** Column 0 to 10,241 is the left hemisphere and 10,242 onwards is the right. So "16000-20484 = limbic" (MersivMedia) is just the last ~4,200 points of the right hemisphere's list. It is not limbic cortex.
2. **Mesh order inside a hemisphere.** fsaverage meshes are made by splitting an icosahedron again and again. The vertex list follows that splitting order, not anatomy (VaseAi finding, web-findings). Meta's own code relies on this:
   - `get_hcp_labels` takes the full-resolution fsaverage label vertices;
   - it keeps those with index below 10,242 to get fsaverage5 [upstream].
   So the low numbers form a coarse grid over the whole hemisphere, and higher numbers fill in the gaps. A range like 0 to 3,500 is dots spread over the entire left hemisphere, not one region. (The "coarse grid" reading is inferred from that code. Confirm it with the plot test below.)

A third, separate problem: subcortical names (amygdala, NAcc, hippocampus) cannot come from the cortical output at all.

### Plot test (do once at build time) [ours]

1. Make a mask of vertices 0 to 3,499. Plot it on fsaverage5 with nilearn. **Expect dots all over the left hemisphere, not one blob.**
2. Make a mask from `get_hcp_roi_indices("V1")`. **Expect one patch at the back of each hemisphere.**
3. If test 1 shows one tidy blob, stop and re-check every assumption in this file.

### Repos that make this mistake (do not copy their scoring)

| Repo or Space | What it does | Source |
|---|---|---|
| hmb/tribe2 (HF Space) | `ZONE_VERTEX_RANGES`: Frontal 0-3500 ... Visual 14500-20484 | web-findings |
| basenewmedia/neurolens | Prefrontal 0-2500, Limbic 3000-4500, Visual 8000-12000 (crosses both hemispheres) | web-findings |
| MersivMedia/tribe-v2-skill | visual 0-4000, auditory 4000-8000 ... limbic 16000-20484 | web-findings |
| coygg/tribe-v2-worker | "emotional" = columns 0-5000, "attention" = 5000-15000 | web-findings |
| Rajkumar2002-Rk/CineNeuro | amygdala_region = slice(6144, 8192), reward_circuit = slice(12288, 14336) | web-findings |
| DojoCodingLabs neuro-testing | visual_cortex = range(0, 3500), "Amygdala-adjacent cortex" 8000-8300, mirrored with +10242 | web-findings |
| luckycat210/tribe-v2-brain-api | 14 "regions" such as Hippocampus 4500-4700 | web-findings |
| idkbutitworks/NeuralLens | Fractions of the array: 0.00-0.22 = visual cortex, etc. | web-findings |
| ndpvt-web/neuroscore | amygdala = (4200, 4400) + (14400, 14600). Code says "For MVP, we use approximate index ranges" | web-findings |
| Vortexfilms/vortex-neural-qc | Salience = 3200-3600 + 8100-8500 + 13400-13800 + 18400-18700 | web-findings |
| NishithP2004/neuropitch-env | STS 2400-3200, TPJ 8700-9600, Broca_45 12900-13600 | web-findings |
| CharlieeeWU/mint-brain-analyser | The array split into quarters ("Visual" = last quarter) | web-findings |
| ceh-vedant/script-brain-optimizer | Fractional slices of each hemisphere (Visual 0.00-0.15, ...) | web-findings |
| siddyviddy/neurallens-tribe-api | Vertices 0-3999 in five blocks of 800 | web-findings |
| oscardevz/synapthic-api | V1 = 0-800, Broca = 4500-5100 | web-findings |
| Axeom/tribe-engage | `vertex_start`/`vertex_end` ranges | web-findings |
| VaseAi/tribe-v2-brain-heatmap (also mike2505, imrayzah) | L_V1 = 0-400 ... L_insula = 10050-10242 | web-findings |
| babesespresso/tribev2 (MULTITUDE.MEDIA) | "Lobes" from index ranges (first 15% of each hemisphere = occipital) | web-findings |
| jcarljuson/n-cope | "TPJ spans indices 1800-3400" | web-findings |
| nestorguerra/praevia-neuroimpact | "ROI mapping v0.2" vertex slices | web-findings |
| vanjaoljaca/tribev2-video-worker | "Rough cortical section" index slices | web-findings |
| RudraanshBhati/tribe-v2-emotion-eval | Index slices (author: "not anatomically validated") | web-findings |
| yautungsky/braindance | "NAcc" is an `np.arange` placeholder slice | web-findings |
| dk700000/neuroscale-tribe-engine | Position-in-hemisphere heuristic (self-described) | web-findings |
| nandhanalahari/Cortex | Falls back to contiguous bands when atlas masks are missing (code admits they are not anatomical) | web-findings |

**Lesser problem: geometric zones, not an atlas.** These cut the brain by coordinates or angles. It is rough, but at least spatial. We still don't use it:
- amirmushichge/tribeV2_ViralAnalyser (y/z coordinate thresholds);
- eliseorobles/PokemonTribeV2 (pial x, y, z rules);
- metehan777/neuralseo (angle thresholds);
- neural.jesion.pl (Gaussian weights around landmarks).

**Subcortical names on cortical output:**
- fayaspsulfikkar/cerebrum-app ("amygdala" = G_temporal_middle);
- markuel/neuroLoop (target maps name the amygdala);
- Paulo-Borszcz/flicker (fake "subcortical" array);
- georginatours/virality-analyzer (claims NAcc, averages the whole cortex).

---

## 5. Pipeline overview

| Step | Where | What |
|---|---|---|
| 1 | Modal GPU | Video, then events dataframe, then `preds, segments`. Save the raw output, then get off the GPU. recozers' code comment: "GPU function: inference only" |
| 2 | CPU | Sanity checks (§6) |
| 3 | CPU | Per-second line means from saved masks (§8, §9) |
| 4 | CPU | Smooth, then put on the two scales (§9, §10) |
| 5 | CPU | Hook window, peaks, flat stretches, trend (§11, §12) |
| 6 | CPU | Word hits (§13) |
| 7 | CPU | Brain picture at the peak (§14) |
| 8 | CPU | A vs B if two clips (§15) |
| 9 | CPU | `report.json`, then Claude writes plain notes (§16) |

Scoring is cheap numpy work. It runs on CPU: in the skill on your machine, or in a Modal CPU function for the site. It never pays for GPU time. The raw `preds` stay saved, so any reel can be re-scored for free when the rules change.

---

## 6. Sanity checks on every run [ours, using sourced limits]

| Check | Action if it fails |
|---|---|
| `preds.shape[1] == 20484` | Stop. Wrong model or mesh |
| Row count roughly equals clip length in seconds | Warn. Rows were dropped or the TR is not 1 s |
| Segment start times step by 1 s | Warn and use the real start times |
| Any NaN or inf | Stop |
| Clip under 10 s | Warn "output may be flat" (techfreakworm) |
| No Word rows but the reel has speech | Warn "language line has no words" |
| Words found inside silent stretches | Mark them "possible ghost words" (Whisper invents speech on silence: a LinkedIn user, community notes LinkedIn) |
| Speech not in English | Warn: transcription is hard-coded to English [upstream] |
| Mock or fallback output | Refuse to score. Several repos silently swap in fake output (Report "Warning" section) |

---

## 7. The 5 second offset

**What is known:**
- The README says predictions "are offset by 5 seconds in the past, in order to compensate for the hemodynamic lag" [upstream]. So the row at second t lines up with what was on screen at second t.
- The paper says training fed stimulus window [-5, T-5] to predict fMRI window [0, T] (quoted in `the build notes` §6).
- **Rule: do not shift the output again.**

**Who got it wrong or risks it:**
- infi02/tribe-worker applies HRF lag correction to output that is already shifted (flagged in web-findings).
- nm05/neuroadgen throws away the first 5 s "for hemodynamic lag".
- Varnan-Tech `local_analyze.py` sets `hrf_offset = 5`. How it is used was not recorded. Check before copying anything from it.
- MECI-Lab did it right: the study "does not add a second shift".

**Other time traps:**
- Nicopotas05/Claudetribev2 assumed about 2 Hz. TRIBE outputs 1 Hz.
- Prakhar's Replicate timeline is about 2 Hz. That is their own resampling, not TRIBE's rate.
- DataCamp saw peaks around 5 to 6 s into clips. My reading is a slow start, not a missing shift. The test below settles it [unverified].

**One-time test [ours]:**
1. Make a 30 s clip: black and silent 0 to 12 s, one clear spoken sentence at 12 to 15 s over black, then black and silent to 30 s.
2. Run it. The hearing and language lines should rise around 12 to 15 s (a little later is fine, since the blood-flow response is slow).
3. If the rise lands around 17 to 20 s instead, the output is not pre-shifted in our setup. Stop and investigate before adding any shift.
4. Check the Word rows. If Whisper invented words in the silent parts, write that down.
5. Record the result once in `METHOD.md` (see `VALIDATION.md` §5.5). Never tune the offset on retention data.

---

## 8. Atlases: mapping vertices to real regions

### 8.1 HCP-MMP1 (Glasser) via `tribev2.utils`: primary

These functions exist upstream (signatures read from code) [upstream]:

| Function | What it does |
|---|---|
| `get_hcp_labels(mesh="fsaverage5", combine=False, hemi="both")` | Dict of parcel name to vertex indices. With `hemi="both"` each parcel's left and right vertices are joined |
| `get_hcp_roi_indices(rois, hemi="both", mesh="fsaverage5")` | Vertex indices for one name or a list of names |
| `summarize_by_roi(data, hemi="both", mesh="fsaverage5")` | Mean per parcel for a **1-D** vector, so loop over seconds |
| `get_topk_rois(data, hemi, mesh, k=10)` | Top k parcel names for a 1-D vector |

Notes:
- **Names.** Upstream strips the `L_`/`R_` prefix, the `_ROI` suffix and the `-lh`/`-rh` tags. So names look like `V1`, `MT`, `44`, `PGi`.
- **No wildcards.** `get_hcp_roi_indices` supports `"X*"` and `"*X"` wildcards. Don't use them. For example `"A*"` would also grab `AIP`. Use exact names only.
- **Unknown labels.** Skip any unknown or medial-wall label if one appears (for example `"???"`) [unverified].
- **Size.** 180 parcels per hemisphere (BERG model card: "180 bilateral Glasser HCP-MMP1.0 regions"; Mammbo/NeuroProfile groups to `(T, 360)`).
- **Heavy first call.** `get_hcp_labels` downloads MNE's sample dataset and the HCP-MMP parcellation through `mne` [upstream]. That is one more reason to build masks once (§8.5).

### 8.2 Yeo-7 networks: cross-check

- Files: `lh.Yeo2011_7Networks_N1000.annot` and `rh.Yeo2011_7Networks_N1000.annot` for fsaverage5.
  - exhuman777 loads them with nibabel. They need FreeSurfer or a mirror, because nilearn does not fetch them.
  - Varnan-Tech's `local_analyze.py` downloads the CBIG copies.
- The 7 networks: Visual, Somatomotor, Dorsal Attention, Ventral Attention, Limbic, Frontoparietal, Default. These are the standard Yeo 2011 names. **Read the names from the annot file. Don't assume the order.**
- Drop the medial wall, as exhuman777 does.
- Avoid projecting the Yeo MNI volume to the surface with `vol_to_surf` (shi3z, theisaacmed/Greenlight). shi3z notes the boundaries come out approximate.

### 8.3 Destrieux via nilearn: optional cross-check

- `nilearn.datasets.fetch_atlas_surf_destrieux` (used by AshwinJ127, and the same atlas by brainiac, MECI-Lab and Reeled In).
- Repos count 146 to 150 labels in total, depending on which unknown labels are dropped (launchpointhq 146, spike-tribe 148).

### 8.4 Schaefer

Schaefer 100/200/400/1000 is used by pif-laborman, Sbrvl, infi02, morady0213 and selfede. We don't need it.

### 8.5 Mask build rules [ours]

1. Build the masks once, in the GPU image or a one-off script. Save:
   - one boolean array of length 20,484 per line;
   - a JSON with: parcel names, vertex count per hemisphere, atlas source, tribev2 commit, date.
   Call it `masks-v1`.
2. Checks:
   - every mask has vertices in both hemispheres;
   - no vertex is in two lines;
   - print the counts.
3. After that the scoring code needs only numpy and scipy, not tribev2 or mne.

---

## 9. Our four lines

### 9.1 v1 masks (HCP-MMP1 parcel names, exact)

| Line | Plain label in reports | v1 parcels | Taken from | Cross-check |
|---|---|---|---|---|
| **Seeing** | predicted visual response | V1, V2, V3, V4, V3A, V3B, V6, V6A, MT, MST | techfreakworm "Engagement" set, visual part | Yeo-7 Visual |
| **Hearing** | predicted auditory response | A1, LBelt, MBelt, PBelt, A4 | techfreakworm "A1, belt areas, A4, A5" | Destrieux transverse temporal + planum temporale (Reeled In's auditory group). Yeo-7 has no auditory network (auditory cortex sits inside Somatomotor; general knowledge) |
| **Language / meaning** | predicted language response | 44, 45, IFSa, STSdp, STSvp, STGa, TE1a, A5, PSL, SFL, 55b | techfreakworm "Language" set | None clean in Yeo-7 |
| **Attention** | predicted attention-network response (**not** viewer attention or retention) | Dorsal: FEF, LIPv, LIPd, VIP, MIP, AIP, IP0, IP1, IP2. Ventral: TPOJ1, TPOJ2, PFm, IFJa, IFJp | techfreakworm "Attention" set, minus DLPFC parcels and minus PGi/PGs | Yeo-7 Dorsal Attention + Ventral Attention |

The belt names (LBelt, MBelt, PBelt) are standard HCP-MMP1 names. The research only says "belt areas". **Check every name against the `get_hcp_labels` keys before use.**

### 9.2 Choices made [ours]

- **A5** is in both of techfreakworm's Engagement and Language sets. We put it in language only, so no parcel sits in two lines.
- **Attention = dorsal + ventral only** [ours; your recorded decisions only say "attention", so confirm with him]. techfreakworm's set also has DLPFC parcels (p9-46v, a9-46v, 9-46d, 46, 8C, i6-8, s6-8). Those are frontoparietal control, so we leave them out.
- **PGi and PGs** are listed by techfreakworm under ventral attention and again under "self-relevance". They are angular gyrus, which in Yeo-7 falls mostly in Default (general knowledge, unverified here). Left out of v1. The Yeo cross-check decides whether they come back.
- techfreakworm's other Engagement parcels (the remaining STS subdivisions, TE1p, TE2p) are not used.
- **Both hemispheres pooled.** Each line is the mean over all its mask vertices, as techfreakworm does. A left-only language line is a later option (brainiac uses left-only VWFA; rohany395 uses left-only Broca).

### 9.3 Cross-check test [ours]

On the first real reel, correlate each HCP line with its Yeo or Destrieux version over time.
- Starting expectation: r of 0.7 or more.
- If it is lower, inspect the masks before trusting the line.

### 9.4 Extra lines kept for calibration only (not shown by default)

`VALIDATION.md` §5.6 lets the dev reels choose between these, so scoring must compute and store them:

| Line | Formula | Source |
|---|---|---|
| Overall strength | Root-mean-square over all 20,484 vertices per second: `sqrt(mean_v(P[t, v]^2))` | Sahu & Pandey "global field power" (arXiv 2607.01400) |
| Pattern change | Change in the whole-cortex pattern between neighbouring seconds. Exact distance measure [unverified]; start with 1 minus the correlation between rows t and t-1 [ours] | MECI-Lab |

### 9.5 Lines we do NOT build

We don't build emotion, reward, desire, memory, social, trust or "virality" lines. Why:
- Going from a region to a feeling is reverse inference (flagged for neuralrank in web-findings).
- Reward areas need subcortex, which is not in the output.
- Nobody has validated any of them.

---

## 10. The maths, step by step

Notation: `P[t, v]` = raw prediction at second t, vertex v. `M_k` = mask for line k.

1. **Line mean.** `L_k[t] = mean of P[t, v] over v in M_k`. Use signed values, not `|P|`. Absolute values mix "lower than usual" with "higher than usual" [ours]. techfreakworm also takes a plain mean.
2. **Smooth.** `S_k = gaussian_filter1d(L_k, sigma=2, truncate=3)` along time.
   - The values come from techfreakworm ("sigma = 2 s, truncate = 3").
   - **Order [ours]:** we smooth first and standardise second. techfreakworm z-scores first, then smooths. Our way, "z = +1" means one standard deviation of the curve the user actually sees.
3. **Detrend for detection only.** `D_k = S_k minus its straight-line fit over time`. This is JoshW-dev's fix for peaks bunching at the end of the clip.
4. **Within-reel z ("shape").** `Z_k[t] = (D_k[t] - mean(D_k)) / sd(D_k)`. Used only to find peaks and flat stretches inside one reel.
5. **Shared scale.** `R_k[t] = (S_k[t] - mu_ref_k) / sd_ref_k`. Used for anything compared across reels (§11).
6. **Combined line.** `C[t] = mean of the 4 Z_k[t]`, and `C_shared[t] = mean of the 4 R_k[t]`. Equal weights [ours]. It helps locate events. It is not a score.
7. **Trend.** The slope of the straight-line fit of each `R_k`, in units per 10 s. Report it as rising, flat or falling. Flat = slope between -0.2 and +0.2 per 10 s (starting point) [ours]. Keeping the trend as its own number means detrending in step 3 doesn't hide a slow fade.

---

## 11. Normalisation: the shared scale

### Pitfalls others hit

| Pitfall | Who | What happens |
|---|---|---|
| Each clip scaled to its own 0-100 (or 0-1) | Reeled In; amirmushichge; luckycat210; many Spaces | Clips can't be compared. Reeled In: "on a known boring-vs-engaging pair, it called the winner backwards". They fixed it with one shared scale per test (95th percentile reference). luckycat210's code warns the strongest region "always lands near 95 … regardless of how good the content actually is" (Report §D) |
| z over all vertices and all seconds at once | Arrnnnaav/neuroux; vishnuverse-in/ad-brain-scorer | neuroux got an "everything ties" bug |
| z across the 7 network means of one time-averaged clip | Varnan-Tech | Throws away time completely |
| Totals over the clip | kumard3/cortext (`preds.sum()`); ifesiTinkering (sum per second) | Cortext found total activation tracks text length at r ≈ 0.97, so it ranks by peak instead |
| Averaging the whole clip into one vector | metehan777, Varnan, PokemonTribeV2, the memorability paper | Hides the hook and the dips. spike-tribe flags that mean-pooling "may wash out the hook" |

### Our shared-scale plan [ours, built on Reeled In, Prakhar, nandhanalahari/Cortex and yahiacuda]

| Stage | When | Scale | Label shown |
|---|---|---|---|
| 0 | Single reel, no reference yet | Within-reel shape only | "relative to this reel's own average" |
| 1 | A vs B, no reference yet | Pool both clips' smoothed lines. Mean and SD per line from the pooled seconds. Both clips go on that | "pair scale" (valid only inside this comparison) |
| 2 | After about 20 of your own reels | `mu_ref_k`, `sd_ref_k` from all seconds of those reels. Store stats for both the smoothed and the unsmoothed lines | "ref-v1 (n reels, date)" |

Rules for the reference:
- **Freeze it.** Change it only on purpose, and bump the version. Old reports keep their old label. The saved raw `preds` let us re-score anything.
- **your own reels only.** Same niche and style. MECI-Lab found results did not carry across channels.
- **Other creators' reels** (for example swipe-file reels) are scored on your own reference, but never added to it.
- Prakhar took mu and sigma from "a few dozen generic clips with no engagement labels". Our reference has the same weakness (no labels) but is at least his own content.

---

## 12. Hook window, peaks and flat stretches

### 12.1 Hook window (0 to 3 s)

- **Rows:** the seconds starting at 0, 1 and 2 (three rows).
- **Same window elsewhere:** rippere ("hook [0-3s]"), Ochakov64, theisaacmed/Greenlight, basenewmedia, cerebrum-app (first 3 TRs), luckycat210 (`hook_ratio`).
- **Report:** per line, the mean over those rows, on the shared scale (or pair scale), using **unsmoothed** lines [ours]. Sigma-2 smoothing would blend in seconds 3 to 6.
- **Caveats:**
  - Only 3 data points.
  - The blood-flow signal is slow. The memorability paper notes "a 3 s clip gives only 3-4 samples".
  - The first seconds may be a warm-up.
- **Best use:** comparing two hooks on the same body, on one scale.

### 12.2 Peaks and flat stretches (all starting points)

| Item | Rule | Source |
|---|---|---|
| Peak | Local maximum of combined `C` at +1.0 or more | exhuman777 and Varnan-Tech (z > +1 = keep) |
| Peak spacing | At least 4 s from a higher peak, picked greedily | Sahu & Pandey (greedy, at least 4 s apart); Greenlight (`find_peaks`, about 4 s apart) |
| Peaks reported | Top 3 | ifesiTinkering took the top 3 seconds |
| Flat stretch | Combined `C` at -1.0 or less for 4 or more consecutive seconds | exhuman777 ("z < -1 for at least 4 s"); Varnan-Tech (abs(z) > 1.0 for 4 timepoints) |
| Merge | Flat stretches 1 s or less apart become one | [ours] |
| Edges | First 2 s and last 2 s are marked "edge, lower confidence". No peaks in the last 2 s | MoburstAI (drops the last 2 timepoints from peak search as artefacts); JoshW-dev (trim edges) |
| Black frames | Seconds with a cut to black are left out of peak-finding | christopher-inegbedion/video-performance-analyzer |
| Driving lines | For each event, list the lines whose own `Z_k` is beyond +1.0 or -1.0 in that window | exhuman777 notes which networks are up or down |
| Strong flat stretch (needs the stage 2 reference) | Also mean `C_shared` of -0.5 or less over the stretch | [ours] |

**Why "strong" matters.** Within-reel z guarantees every reel has ups and downs. Even a uniformly good reel gets "flat stretches". The shared-scale check separates "low for this reel" from "low for your reels". It is the same trap as luckycat210's "always near 95".

**Why detrend, edges and spacing.** JoshW-dev found "4 of 5 test videos show peaks clustering in the final few seconds". The causes were linear drift, smoothing edge artefacts and duplicate neighbouring peaks. The fix was detrending, z-scoring, trimming edges and a minimum peak spacing.

**Later option.** MoburstAI labels curve shapes (front-loaded, back-loaded, U-shape, peak-middle, flat). That could help Claude's notes. Not in v1.

---

## 13. Word hits

**Source:** the Word rows in the events dataframe TRIBE itself used: `type == "Word"`, with `text`, `start`, `duration`, `sentence` [upstream]. Don't re-transcribe separately, or the timings won't match. video-performance-analyzer writes its own faster-whisper timings into TRIBE's cache for exactly this reason.

**Method [ours; loosely based on Gui em Produção's rule of thumb "a language-region spike on a phrase means it carries weight", a claim only]:**
1. Map each word to the row or rows whose segment overlaps `[start, start + duration]`.
2. Word value = the **unsmoothed** language line at that row, on the shared or pair scale. Take the max if the word spans two rows. With no scale yet, use within-reel `Z`.
3. Join neighbouring words in the same or the next second into one phrase.
4. Keep phrases with a value of +1.0 or more. Report the top 5 (starting points).

**Caveats to print with the word hits:**
- **Coarse timing.** One row per second and a slow signal means several words share a second. All we can say is "the language line was high in the second this phrase was spoken". It does not prove the phrase caused it.
- **Ghost words.** Whisper can invent words on silent stretches (a LinkedIn user). Mark words in near-silent audio as "possible ghost words" [ours; needs a per-second loudness check].
- **English only.** Transcription is hard-coded to English [upstream]. Hindi or Hinglish speech will come out wrong. Warn on non-English reels.
- **On-screen captions probably don't count.** The Word rows come from the audio transcript [upstream `get_audio_and_text_events`]. On-screen text only reaches the model through the video encoder [inference from the code, not tested].
- **Unmatched words.** Upstream runs `AddSentenceToWords(max_unmatched_ratio=0.05)`. MECI-Lab dropped videos whose unmatched-word ratio was above 0.05. Log any warning it raises.
- **Lyrics.** Music with lyrics also produces Word rows.

---

## 14. Brain picture at the peak

- **Which second:** the top combined peak.
- **Plot call:** `PlotBrain(mesh="fsaverage5")` or `PlotBrainNilearn`. Upstream `plot_surf` takes `norm_percentile`, `vmin`, `vmax`, `symmetric_cbar` and `cmap` (default `"hot"`) [upstream]. Common settings elsewhere: `cmap="fire"`, `norm_percentile=99` (ifesiTinkering, recozers).
- **Colour scale trap.** `norm_percentile` rescales each picture by its own values (upstream `robust_normalize`). That is fine for one picture alone. For A vs B, or reel against reel, pass `norm_percentile=None` and the same `vmin`/`vmax` for both. Starting point: the 99th percentile of absolute values pooled over both clips' peak rows [ours]. DataCamp also clips at the 99th percentile of absolute values.
- **Servers with no screen:**
  - use `PlotBrainNilearn` (PR #80);
  - thecmdrunner reports that `PlotBrainPyvista` segfaults on such servers and that `plot_timesteps` broke the Nilearn backend;
  - recozers ran the plotter under Xvfb.
- **Views:** at least left and right side views. recozers shows the left side only.
- **Caption:** "predicted average-brain response at 0:12". No labels that tie a region to a feeling.

---

## 14b. Brain view on the private dashboard (9 Oct 2026)

The reel page's 3D brain you can scrub, its Areas tab and its numbers file (CSV). Built by `strategist/brain_assets.py`. The area tables come from `scoring/build_atlas.py` (`scoring/masks/atlas-v1.json`). All of it is [ours] unless tagged.

- **What it shows:** the model's own 1-s rows, `P[t, v]`, **unsmoothed**. The four lines are smoothed (§10 step 2), so a lane and the brain at the same second can differ a little.
- **One colour scale for the whole reel:**
  - `vmax` = the 99th percentile of `abs(P[t, v])` over every cortex point (HCP label not 0, so the medial wall is left out) and every second of that one reel, rounded to 6 decimals. The 99th percentile follows DataCamp, as in §14.
  - Stored at 255 steps (int8): `q = clip(rint(P / vmax * 127), -127, 127)`. -128 is never used. The round-trip error is at most `vmax / 254`, and about 1% of values clip at the ends.
  - Fixed for the reel. It is never recomputed per second.
- **Colours:** `PuOr_r` (diverging, never red/green), with the same thresholds `peak.png` uses (`BRAIN_GREY_BELOW` 0.15 and `BRAIN_FULL_AT` 0.5 in `scoring/score.py`). Below `0.15 x vmax` only the grey sulcal shading shows, and colour is full from `0.5 x vmax` up. Medial-wall points stay grey.
- **Legend:** "one colour scale for this whole reel". Never "vs this reel's own average": these are raw model output around the model's zero, not the within-reel z of §10 step 4.
- **Area means:** §10 step 1 applied to each parcel, the signed mean of `P[t, v]` (float32, before the int8 step) over the parcel's points, per second.
  - HCP-MMP1: 180 areas per side, left and right kept apart. Yeo-7: 7 networks, both sides together. Plus the four lines' means (§10 step 1, before smoothing).
  - Stored at 4 decimals. The browser never averages the int8 maps.
- **Area order:** fixed atlas order. Yeo network 1 to 7 first (each HCP area sits under the network that holds most of its points), then the Glasser index. Never sorted by value, no top-N.
- **"Coloured on the brain at this second"** (the Areas tab): `abs(area mean) >= 0.15 x vmax`, the same grey threshold. The sign gives warm or cool. Rows never move.
- **Sparklines:** one y-scale for the whole panel, from `vmax`. Never one per row.
- **No per-area scales:** an area is never coloured by its own within-reel z. That would be per-area autoscaling, the per-clip 0 to 100 trap in §11. A per-area within-reel z may appear only in the numbers file.
- **`peak.png` keeps its own-row scale, so its colours differ.** The picture at the top peak (§14) takes `vmax` from that one second: the 99th percentile of `abs(P[row])` over all 20,484 points. the demo fp32 job: 0.5705 at 0:37 for `peak.png`, against 0.4871 for the reel-wide scale. It is not re-rendered, because that would need a new `SCORING_VERSION`.
- **Nothing across reels :** each reel has its own `vmax`, so the same colour means different values on two reels. No file holds two reels, and two reels' maps or numbers never sit side by side.
- **Names:** HCP areas by short code only, with no function names. Yeo names verbatim ("Yeo network 5: Limbic"), with the hint that atlas names mark places on the cortex, not feelings.
- **Later:** the stage 2 reference scale (§11) could replace the per-reel scale once about 20 of his own reels exist.

---

## 15. A vs B compare

Rules [ours unless cited]:
1. **One scale.** Use the reference if it exists, else the pair scale. Never each clip's own scale (Reeled In).
2. **Like for like.** Same body with a different hook, or the same script with a different edit. If lengths differ, compare the aligned seconds up to the shorter clip and report the extra seconds separately.
3. **Per line, report:**
   - mean over the clip;
   - mean over the hook window;
   - the difference curve B minus A, per second.
4. **Where they differ most.** Use DataCamp's method: `preds_a[t] - preds_b[t]` per vertex, plus the per-second L2 norm of that difference. Report the top 3 seconds and a difference brain picture (symmetric colour scale).
5. **"Noticeably higher"** = a gap of 0.5 or more on the shared scale (starting point).
6. **No overall winner.** Say it per line: "B had a higher predicted hearing response in seconds 0 to 3". Reeled In let the user pick the goal line. you can pick which line he cares about.
7. **Gaps are hints, not results.** The model gives the same output for the same input, so a small gap is not model noise. It can still mean nothing. Until calibration passes, treat any gap as a reason to test with a real audience (the Demo guide in `origin/community notes points to Instagram Trial Reels and YouTube title tests).

---

## 16. Output contract (what scoring hands to Claude and the site)

A sketch of `report.json`. Field names are a proposal [ours]. `the build notes` §12 holds the interface sketch. Keep the two in sync.

```json
{
  "framing": "predicted average-brain response",
  "scoring_version": "0.1",
  "masks_version": "masks-v1",
  "scale": {"mode": "within-reel | pair | ref", "ref_version": "ref-v1 (20 reels, 2026-xx-xx) or null"},
  "offset": "model-aligned, no extra shift (checked on <date>)",
  "clip": {"seconds": 41, "rows": 41, "language": "english"},
  "warnings": ["clip under 10 s", "possible ghost words at 0:18"],
  "time_s": [0, 1, 2],
  "lines": {
    "seeing":    {"shape_z": [], "shared": [], "trend_per_10s": 0.0},
    "hearing":   {"shape_z": [], "shared": [], "trend_per_10s": 0.0},
    "language":  {"shape_z": [], "shared": [], "trend_per_10s": 0.0},
    "attention": {"shape_z": [], "shared": [], "trend_per_10s": 0.0}
  },
  "combined": {"shape_z": [], "shared": []},
  "calibration_only": {"overall_rms": [], "pattern_change": []},
  "hook_0_3s": {"seeing": 0.0, "hearing": 0.0, "language": 0.0, "attention": 0.0},
  "peaks": [{"t": 12, "value": 1.4, "driving_lines": ["seeing"], "edge": false}],
  "flat_stretches": [{"start": 22, "end": 27, "mean": -1.3, "driving_lines": ["language"], "strong": null, "edge": false}],
  "word_hits": [{"phrase": "...", "start": 8.2, "end": 9.0, "value": 1.6, "ghost_flag": false}],
  "brain_picture": {"t": 12, "path": "peak.png", "vmin": 0.0, "vmax": 0.0},
  "compare": null,
  "raw": {"preds": "preds.npy", "segments": "segments.json", "events": "events.json"}
}
```

### Rules for Claude's plain notes

- Use "predicted average-brain response". **Every claim cites a time range and a line from the JSON.**
- **Banned words:** views, viral, virality, reach, CTR, watch-time forecast, "will perform", "engagement score", emotion, reward, dopamine, desire, amygdala, NAcc, any 0-100 score, and verdicts like POST, DEPLOY or STRONG.
- **Must say:**
  - until a reference exists, dips are relative to the reel itself;
  - the model predicts an average brain, not your audience. One Instagram creator's line fits: "Treat it as a second opinion next to your real retention graph" (community notes).
- **Edit ideas** are framed as things to test, never as fixes.
- **Why so strict:** "TRIBE produces a curve, and an LLM turns it into words. Several critics note the final judgement then really comes from the LLM" (Report §G). Tying Claude to the numbers limits that.

---

## 17. Differences from `the build notes` §7 (this file wins)

Verifier note, 7 Oct 2026: `the build notes` §7 has since been updated to match this file (masks, step order, overall RMS as calibration only, README as the offset source). The table is kept as a record of what changed.

| Topic | the build notes §7 (before the update) | This file | Why |
|---|---|---|---|
| Attention parcels | Includes DLPFC parcels and PGi/PGs | Dorsal + ventral only; DLPFC and PGi/PGs left out | Our choice [ours] (your recorded decisions only say "attention"). PGi/PGs sit mostly in Default (to confirm with the Yeo cross-check) |
| A5 | In hearing | In language only | No parcel in two lines |
| Order | z-score, then smooth | Smooth, detrend, then z-score | Thresholds then mean "1 SD of the curve shown" |
| Scale | z over the video's own timeline | Two scales: within-reel z for events, shared scale for comparisons | A within-reel z alone has the per-clip problem Reeled In hit |
| Overall RMS line | One of five shown lines | Stored for calibration, hidden by default | Spec says 4 lines; RMS is a `VALIDATION.md` dev-reel candidate |
| Offset source | Gonzih "baked in" | Upstream README line 32, plus the one-time test | Primary source now read |

---

## 18. What scoring must store for calibration

The full protocol (dev and holdout reels, exit rate, match window, chance by circular shift, pass bar) is in `VALIDATION.md` §5. Scoring's job is to make that possible:

- **Per reel:**
  - raw `preds.npy` (60 s at float32 is about 4.9 MB);
  - segment start times;
  - the events dataframe (Word rows);
  - `report.json`;
  - `scoring_version`, `masks_version` and `ref_version`;
  - a hash of the clip.
- **Saved before the analytics are pulled**, so the flags can't be bent to fit (`VALIDATION.md` §5.3).
- **Frozen flag rule.** The flat-stretch rule in §12 is what `VALIDATION.md` calls the "flagged dip". Once `METHOD.md` freezes it, scoring must not change it silently. Any change means a new `scoring_version`.
- **No tuning to fit.** Don't tune thresholds until they match. Alkimia fitted and reported on the same 15 reels and kept recalibrating ("Recalibrar score").
- **No outcome models for now.** 20 to 30 reels is too few to train anything. spike-tribe at n=61 found nothing beyond followers.

---

## 19. Catalogue of formulas others use

### 19.1 What we take (adopt or adapt)

| Who | What they do | We take | Source |
|---|---|---|---|
| techfreakworm/tribev2-brain-timeline | HCP parcels, mean per TR, z over the timeline, Gaussian sigma 2 s (truncate 3). Curves: Attention, Engagement, Virality, Language, Self-relevance | **Adopt** the method and the parcel lists for our 4 lines. **Reject** the "Virality proxy" | Report §D.2; web-findings |
| exhuman777/tribe-v2-engagement-analysis | Yeo-7 means; `E = z(DAN) + z(VAN) + z(Limbic) + z(Visual) - z(DMN)`; cut where z < -1 for 4 s or more; keep where z > +1 | **Adapt** the peak and flat-stretch thresholds. **Reject** the hand-signed E formula | Report §D.2 |
| Varnan-Tech meta-tribeV2-skill | abs(z) > 1.0 held for 4 timepoints | **Adapt** the 4-timepoint rule only | web-findings |
| Sahu & Pandey (arXiv 2607.01400) | RMS over all vertices per second; peaks at least 4 s apart; partial correlation after removing a [1, t, t²] trend | **Adopt** RMS as a calibration-only line, the 4 s spacing, and position control (`VALIDATION.md`) | Report §D.1, §E |
| Reeled In | Moved from per-clip scaling to one shared scale per test | **Adopt** the shared scale | Report §D |
| JoshW-dev/tribev2-test | Fixed end-biased peaks with detrending, z-scoring, edge trimming and minimum spacing | **Adopt** the fix | web-findings |
| MoburstAI/tribe-v2-analyzer | Drops the last 2 timepoints from peak search; curve-shape labels | **Adopt** the edge rule; curve shapes later | web-findings |
| DataCamp tutorial | `preds_a[t] - preds_b[t]` and the per-second L2 norm of the difference | **Adopt** for A vs B "where they differ" | web-findings |
| MECI-Lab | Destrieux profiles; 5 s windows; no second shift; cubic position residualisation; pattern change | **Adopt** no double shift, position control and pattern change (calibration only) | Report §E; web-findings |
| yahiacuda/tribe-brain-analysis | Sustained peaks above mean + 1 SD, with thresholds pooled across videos | **Adapt** (pooled = shared scale) | web-findings |
| nandhanalahari/Cortex | New takes re-normalised with the original ad's stats | **Adapt** (same idea as the pair and ref scale). Reject its formula | web-findings |
| Prakhar-Bhartiya content-signal | Fixed mu and sigma from a reference corpus | **Adapt** the fixed reference idea. Reject everything else (see 19.2) | Report §D.2 |
| christopher-inegbedion/video-performance-analyzer | Cuts to black left out of peak-finding; `opening_2s`, trough, decay | **Adopt** the black-frame exclusion | web-findings |
| Square-Zero-Labs (Fuzz Puppy) | `summarize_by_roi` per second; top-ROI peak and mean; ROI group means | **Adapt** the group-means idea. Reject top-ROI score as a performance signal (r = -0.82 at n=10 is a claim in a video only) | Report §E; community notes YouTube |
| spike-tribe-validation | PCA or 148 Destrieux means + log(followers) + duration; logistic regression; 5-fold CV; bootstrap | Keep as the honest test design if outcomes are ever modelled. Not now | Report §C, §E |

### 19.2 What we reject

**Any "virality" score, view band or performance verdict is rejected outright.** None has been validated, and the careful tests in §2 say there is nothing to validate it against.

| Who | Formula or rule | Why rejected | Source |
|---|---|---|---|
| Varnan-Tech | View bands: "VAN > +0.5 & DMN < 0: Viral potential (100k+ views)"; "DMN > +0.5: High flop risk (<10k views)"; Z mapped to 0-100 | Unvalidated view bands. Its own misses (a 2.3M-view video scored "boring") are explained away | Report §D.2, §E |
| Prakhar-Bhartiya | Reward 30%, Emotion 25%, Attention 20%, Social 15%, Novelty 10%; each `sigmoid(sign*(x-mu)/sigma)*100` | Hand weights; reward and emotion labels by reverse inference; no NAcc. A reuser (hass-disrupt) notes "TRIBE itself does not produce a 'virality score'" | Report §D.2; web-findings |
| techfreakworm | "Virality proxy" from vmPFC/mOFC/pgACC/mPFC | Reward proxy with no striatum; not validated | web-findings |
| Reeled In | `E = 0.30 DMN + 0.25 Vis + 0.20 Lang + 0.15 Aud + 0.10 Mot` ("a prior we set, not fit to outcome data"); retention = last third / first third | Hand weights; their own metrics were later "REMOVED entirely" | web-findings |
| rippere/tribe-social | Weighted HCP ROIs (social 0.30, attention 0.25, ...), min-max over the corpus; POST at 65+, REVISE 40-64.9, RETHINK below | Failed its own gate (r = 0.25) | Report §E |
| theisaacmed/Greenlight | `engagementScore = 35*hook/100 + 30*peakDensity + 20*avgEng - 15*deadZonePenalty`; bands at 72 and 55, lowered because z-scores "rarely exceed" the spec | Hand-made score; bands moved to fit | web-findings |
| MoburstAI | Weights 0.30/0.25/0.25/0.15/0.05; 1-10 score `1 + 9*clip((raw - 0.3)/0.5)`; no offset handling | Hand-made score | web-findings |
| JoshW-dev | NES = 0.35 ARS + 0.25 EII + 0.25 HSS + 0.15 CAS | Hand weights | web-findings |
| Ochakov64/ad-virality-analyzer | `virality = clamp(mean(peak_z) * social_mult * 100, 0, 100)`; hand-made retention curves | Virality score; hand-designed | web-findings |
| subkap88-coder/Hook-Brain | `viral = 4.0*(mean_t0 + mean_t1) + 2.0*top100_mean_t0 + ...`; right-hemisphere lead read as "emotional hit" | Hand weights; hemisphere-to-feeling story | web-findings |
| amirmushichge/tribeV2_ViralAnalyser | `mean(abs(preds))` per second, min-max 0-100 per video; `signal = 0.7*activation + 0.3*novelty`; dips at 55 or below | Per-clip scaling; whole brain; thresholds unvalidated | Report §D.1 |
| alkimiaestudio | `score = 1/(1 + exp((std - 0.036)*80))`: steadier curve = higher score | n=15, no holdout, recalibrated several times; the opposite direction from most tools | Report §D.1, §E |
| kumard3/cortext | `total_activation = preds.sum()` | Tracks text length (r ≈ 0.97) | Report §D.1 |
| metehan777/neuralseo | "Neural CTR Score" = 0.34 peak_salience + 0.28 global + 0.20 sustained + 0.18 entropy; time-averaged; angle-based regions | CTR claim; no atlas; no time | web-findings |
| evisdrenova | `emotional_impact = clamp01((max+std)/2)` and similar | Arbitrary maps from whole-brain stats | web-findings |
| DojoCodingLabs | Composite 0.25/0.20/0.20/0.20/0.10/0.05; DEPLOY 70-100, TEST 55-69, ITERATE 40-54, SKIP below | Fake regions; unvalidated verdicts | Report §D.3 |
| hmb/tribe2 | Zone ranges; STRONG at 72+, AVERAGE 50-71, WEAK below 50 | Fake regions; verdict bands | web-findings |
| antfx/brainrot-or-not | `raw = 0.4*avg + 0.6*peak`; `clip(50 + 25*z)`; BRAINROT at 75+ | Verdict bands; hand weights | web-findings |
| vishnuverse-in/ad-brain-scorer | z against the global mean over all vertices and times, then a sigmoid | Global z (the neuroux "everything ties" trap) | web-findings |
| georginatours/virality-analyzer (and Spanish copies) | First segment weighted 1.6x; cites "Knutson Lab NAcc" | No NAcc in the output; whole-cortex mean | web-findings |
| Nicopotas05/Claudetribev2 | Yeo weights (VAN 1.6, Limbic 1.5, ...), sigmoid to 0-100 | Assumes about 2 Hz; hand weights | web-findings |
| babesespresso/tribev2 | `Virality = 0.45*emotion + 0.3*auditory + 0.25*visual`; purchase intent formula | Fake lobes; invented percentages | web-findings |
| siddyviddy/neurallens-tribe-api | `viral_potential = 0.35*DMN + 0.30*emotion + ...` | Uses only vertices 0-3999 with made-up labels | web-findings |
| nestorguerra/praevia-neuroimpact | `100*p75/(p75 + 0.08)`; benchmark delta = score - 60 | Fixed made-up baseline; vertex slices | web-findings |
| anasmk9 | Yeo clusters into 4 KPIs via a weight matrix; spikes at z > +2 | Hand weights | web-findings |
| LucasVillelao/neuro-ads | Neuro Rank = 0.35 hook + 0.25 synergy + 0.20 semantic + 0.20 coherence | Hand weights | web-findings |
| anilp-stack (tribev2 PR #57) | "CPCi" under 40 DO NOT SCALE, 40-70 OPTIMISE, over 70 READY TO SCALE | Formula not shown; media-cost claims unvalidated | web-findings |
| NeuralAds | "Predicted CTR 2.4-3.1%", "Hook score +82" | Claims only; no method | Report §E |
| Hand-made-weight composites in general (Chalupa, Vortexfilms, Wenluo, 1AutumnL3af, ...) | Weighted blends of named "regions" | Weights invented, not fitted | web-findings |

---

## 20. Threshold and settings register (all starting points)

| Setting | Value | Source | Revisit when |
|---|---|---|---|
| Time step | 1 s (use segment start times) | DataCamp, BERG; [upstream] | Never, unless the TR changes |
| Extra offset | 0 s (model already shifted 5 s) | [upstream] README | After the one-time test |
| Gaussian sigma | 2 s, truncate 3 | techfreakworm | After calibration |
| Peak threshold | combined z of +1.0 or more | exhuman777, Varnan | After calibration |
| Peak spacing | 4 s or more | Sahu & Pandey; Greenlight | After calibration |
| Peaks shown | top 3 | ifesiTinkering | UI choice |
| Flat stretch | combined z of -1.0 or less for 4 s or more | exhuman777, Varnan | Frozen in `METHOD.md` before reel 1 |
| Merge gap | 1 s or less | [ours] | After calibration |
| Strong flat stretch | mean shared combined of -0.5 or less | [ours] | After the reference exists |
| Edge seconds | first 2 and last 2 s | MoburstAI; JoshW-dev | After calibration |
| Hook window | rows at 0, 1, 2 s | rippere, Ochakov64, Greenlight and others | Keep |
| Short-clip warning | under 10 s | techfreakworm | Keep |
| Trend "flat" band | -0.2 to +0.2 per 10 s | [ours] | After 10 reels |
| Word-hit cutoff | +1.0, top 5 phrases | [ours] | After 10 reels |
| A vs B "noticeable" gap | 0.5 on the shared scale | [ours] | After calibration |
| Mask cross-check | r of 0.7 or more | [ours] | First reel |
| Reference size | about 20 own reels | [ours], matches the 20 to 30 reel plan | At 50 reels |
| Brain picture scale | shared vmin/vmax, 99th percentile of absolute values | [ours]; DataCamp | Keep |
| `peak.png` scale, as built (§14b) | its own second: 99th percentile of absolute values over all 20,484 points | [ours]; DataCamp | Keep (a change needs a new `SCORING_VERSION`) |
| Brain view scale (§14b) | one per reel: 99th percentile of absolute values over cortex points and all seconds, 6 decimals | [ours]; DataCamp | When the stage 2 reference exists |
| Brain view steps | 255 (int8, -127 to +127) | [ours] | Keep |
| Brain view colours | `PuOr_r`; grey below 0.15 x vmax, full colour from 0.5 x vmax (same as `peak.png`) | [ours] | Keep |
| Brain view length | at most 90 s of rows | [ours] | If the input limit changes |
| Area means | signed mean per parcel per second (HCP-MMP1 180 a side, Yeo-7), 4 decimals | [ours]; §10 step 1 | Keep |
| Area order | Yeo network 1 to 7, then Glasser index; never by value | [ours]  | Never |
| "Coloured on the brain at this second" | absolute area mean of 0.15 x vmax or more; the sign gives warm or cool | [ours] | After 10 reels |

---

## 21. Open questions to settle at build time

1. Does the one-time offset test land at 12 to 15 s? (§7)
2. Do all v1 parcel names exist exactly in `get_hcp_labels` keys? (§9.1)
3. Does the Yeo cross-check support leaving PGi/PGs out of attention? (§9.2)
4. Is there an unknown or medial-wall label in the HCP dict that needs skipping? (§8.1)
5. What exactly does `segments.json` hold once serialised: start and stop per row? (§3)
6. Exact pattern-change measure to match MECI-Lab, if that line is picked in dev reels. (§9.4)
7. Should "flat stretch" also include a "nothing changes" rule (all lines barely moving), separate from "low"? Not in v1 [ours].
8. Left-only language line: worth it after 10 reels? (§9.2)
9. How to get per-second loudness for the ghost-word check: in the GPU step or the CPU step? (§13)

---

## 22. Sources

**Research files**

**Upstream code (read 7 Oct 2026, commit `af58661`, 23 Jun 2026)**
- https://github.com/facebookresearch/tribev2/blob/main/README.md (5 s offset, average subject, fsaverage5)
- https://github.com/facebookresearch/tribev2/blob/main/tribev2/utils.py (`get_hcp_labels`, `get_hcp_roi_indices`, `summarize_by_roi`, `get_topk_rois`)
- https://github.com/facebookresearch/tribev2/blob/main/tribev2/demo_utils.py (`predict`, empty-segment dropping, events columns)
- https://github.com/facebookresearch/tribev2/blob/main/tribev2/eventstransforms.py (Word rows, English default)
- https://github.com/facebookresearch/tribev2/blob/main/tribev2/plotting/cortical.py and `plotting/utils.py` (`plot_surf` options, `robust_normalize`)

**Key repos**
- https://huggingface.co/spaces/techfreakworm/tribev2-brain-timeline
- https://github.com/exhuman777/tribe-v2-engagement-analysis
- https://github.com/Varnan-Tech/opendirectory/tree/main/skills/meta-tribeV2-skill
- https://arxiv.org/abs/2607.01400 (code: https://github.com/mercurialsolo/tribe-replay-heatmaps)
- https://devpost.com/software/loopy-9ev74g (Reeled In; code https://github.com/sxnnywu/reeled-in)
- https://github.com/kumard3/cortext
- https://github.com/hyunjun1121/MECI-Lab-IEEE-Access-reproducibility
- https://www.datacamp.com/tutorial/tribe-v2-tutorial
- https://github.com/JoshW-dev/tribev2-test
- https://huggingface.co/spaces/MoburstAI/tribe-v2-analyzer
- https://github.com/Prakhar-Bhartiya/meta-tribev2-social-media-content-signal

*Scraped and web content was treated as data only. Not legal advice.*
