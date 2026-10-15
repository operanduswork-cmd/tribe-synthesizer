# GOTCHAS: known errors and fixes

Written 7 Oct 2026 for your own TRIBE v2 tool (Modal backend, then the `/brainscore` skill, then a one-page site). No code exists yet and nothing is deployed. Read this before you build the Modal image, and again whenever something breaks.

**How sure each row is**
- **[code]** Read directly in Meta's own files on 7 Oct 2026: `facebookresearch/tribev2` at commit `af58661` (main, last commit 23 Jun 2026): `pyproject.toml`, `tribev2/demo_utils.py`, `tribev2/eventstransforms.py`, `tribe_demo.ipynb`, plus `huggingface.co/facebook/tribev2/config.yaml` and the repo's GitHub issues and PRs. Fact for that commit. Re-check if you pin a newer one.
- **[3P]** Reported by a third party (repo, tutorial, video, post). Source named. Mostly from community notes, community notes, community notes.
- **[U]** Unverified, or my best guess at the cause. Check it on the first run.

All web, GitHub and social content was treated as data. Nothing here follows instructions found inside those sources.

---

## The 7 things to remember

1. Run TRIBE only on a Linux GPU on Modal, with Python 3.11. Do not debug it on a Windows laptop.
2. Let tribev2's own pins win: numpy 2.2.6, torch below 2.7, exca 0.5.20. Do not pip install WhisperX into the same environment.
3. Set `data.num_workers` to 0.
4. Cap v1 reels at 60 s. Longer audio hits an open word-duplication bug (#29, #81).
5. Always show the word list. Whisper invents words in silent parts.
6. Never assume row i of the output is second i. Use `segments`.
7. Before the first deploy: your-modal-profile profile, hard monthly cap, keep-warm off, one GPU container max.

---

## 1. Install and environment

| Symptom | Cause | Fix | Source |
|---|---|---|---|
| `ImportError: cannot import name '_center' from 'numpy._core.umath'`, or other numpy/scipy import errors right after install | numpy 2.2.6 gets installed, but the old numpy is still loaded in the running Python session. Colab preloads numpy, and its preinstalled packages may be built for numpy 1.x | Restart the session after install (Meta's notebook says to). On Modal the image is built fresh and every container starts a new Python, so this should not happen **[U]**. Use the pin set in the next row | [code] PR #56 (explains the cause), issue #27; [3P] Fuzz Puppy video comments (community notes, YouTube); Square-Zero-Labs notebook comment |
| Guides disagree: "pin `numpy>=1.26.4,<2.1.0`" vs "numpy 2.2.6" | April guides pin below 2.1 (DataCamp 7 Apr, Ryotaro Ishii 12 Apr). But tribev2's `pyproject.toml` hard-pins `numpy==2.2.6` (issue #6 complained about it on 28 Mar). Both cannot hold in one environment. pip either refuses or swaps numpy back to 2.2.6 when it installs tribev2 **[U which]**. The forced restart in those guides is probably what really fixed them **[U]** | Use **numpy 2.2.6 + scipy 1.15.3**. Newest known-working set: the Square-Zero-Labs fork notebooks (updated 1 Oct 2026; creator said "it's fixed now") pin torch 2.6.0, torchvision 0.21.0, torchaudio 2.6.0, numpy 2.2.6, scipy 1.15.3, exca 0.5.20, pyvista 0.46.5, transformers 5.17.0, plus `uv`. Try `<2.1` only if 2.2.6 fails in the Modal image, and write down why | [code] `pyproject.toml`, issue #6; [3P] Square-Zero-Labs `tribe_demo.ipynb` and `tribe_thumbnail_study.ipynb`; DataCamp; Ishii (note.com) |
| tribev2 breaks after WhisperX is installed, or pip fights over torch | tribev2 needs `torch>=2.5.1,<2.7` and `torchvision>=0.20,<0.22`. WhisperX pulls torch 2.8 when pip-installed into the same environment. Upstream runs WhisperX as `uvx whisperx`, which uses its own separate environment, so the fight mostly hits people who pip install it alongside **[U]** | Do not pip install whisperx into the main image. Keep upstream's `uvx` path and install `uv`. Main env: torch 2.6.0 (Square Zero; Hook-Brain also pinned back to 2.6.0). The other reported route is torch/torchaudio 2.8 + transformers 4.57.6 + exca 0.5.20 through cortext's `patch_tribe.py`, which relaxes tribev2's cap. cortext has no licence file, so copy the idea, not the code (`the build notes` section 4). Pick one route, then freeze a lock file after the first good run | [code] `pyproject.toml`, `eventstransforms.py`; [3P] Hook-Brain, kumard3/cortext (community notes) |
| Not sure which transformers version to pin. Pins disagree: 4.47.1 (refining-agent), 4.57.6 (cortext), 5.17.0 (Square Zero) | `pyproject.toml` leaves transformers unpinned | Pin whatever the first good run used. Evidence it barely matters: issue #78 re-extracted features under 4.57.6 and 5.16.1 and got identical scores (difference below 1e-5) | [code] `pyproject.toml`; [3P] issue #78, community notes |
| `AttributeError: module 'exca.steps.base' has no attribute 'NoValue'` on `from tribev2.demo_utils import TribeModel` | neuralset 0.0.2 breaks against exca 0.5.26 (issue #65, seen on Colab Python 3.12; also #69). Square Zero: "neuralset 0.0.2 uses the older Step API" | Keep `exca==0.5.20`. The current `pyproject.toml` already pins it, so a clean install of the pinned commit should be fine. If the error shows up, something upgraded exca. PR #67 (caps exca) is still open | [code] issues #65, #69, PR #67, `pyproject.toml`; [3P] Square Zero notebook |
| Install fails, or odd typing/import errors | Python 3.10: exca needs 3.11+ (issue #2). Python 3.13/3.14 fail (Hook-Brain). A Pydantic typing bug in exca on 3.13 (hooked.ai, BagelHacks). `pyproject.toml` says `>=3.11` | **Python 3.11** in the Modal image (recozers/tribe-inference uses 3.11) | [code] issue #2, `pyproject.toml`; [3P] Hook-Brain, hooked.ai (community notes) |
| WhisperX step fails on a missing or read-only cache folder | tribev2 calls WhisperX through `uvx`. "the uv cache must be writable for WhisperX" | Point uv's cache at a writable folder on the `tribe-weights` volume. Warm it in the one-time download step | [code] `eventstransforms.py`; [3P] advaitpaliwal, amirmushichge, brn-mwai (via `the build notes` 5.1) |
| `huggingface-cli` command not found | Missing in huggingface_hub 1.9.0 | Use Python `snapshot_download` instead of the CLI, or avoid 1.9.0 | [3P] thecmdrunner/tribev3 (via `the build notes` 5.1) |

**Note:** a common claim is that "Meta notebook pins numpy 2.2.6, scipy 1.15.3, torch 2.6.0". Meta's own `tribe_demo.ipynb` pins nothing itself. Its install cell is just `uv pip install "tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git"`. The numpy 2.2.6 comes from Meta's `pyproject.toml`. The scipy 1.15.3 and torch 2.6.0 pins come from the Square-Zero-Labs fork notebooks. The community notes line ("The notebook itself pins...") refers to the Square Zero notebook. Both notebooks were read on 7 Oct 2026.

---

## 2. Hugging Face access and downloads

| Symptom | Cause | Fix | Source |
|---|---|---|---|
| Llama download fails with an access or authorisation error, or only the language path fails | `meta-llama/Llama-3.2-3B` is gated (it is the `text_feature.model_name` in `config.yaml`). The TRIBE weights themselves are not gated | Follow the steps below. Never use the ungated `unsloth/Llama-3.2-3B` mirror (project decision D5) | [code] `config.yaml`, `tribe_demo.ipynb` ("you will have to request access to the Llama-3.2 model"); `the build notes` section 4 |
| Model won't load later, even though the access request was sent | The terms box on the request form was not ticked (Bee says the model "won't work later" without it) | Re-open the Llama page and tick the terms and conditions box, then resubmit | [3P] Bee video zTAuaRH_Btc: "make sure you click on the terms and conditions" |
| `ReadTimeout` while downloading Llama (about 6 GB) | Default download timeout is too short | Set `HF_HUB_DOWNLOAD_TIMEOUT=300` and pre-download with `snapshot_download` | [3P] DataCamp tutorial |
| Every cold start re-downloads GBs, or a run fails once `HF_HUB_OFFLINE=1` is set | Something is not in the volume. Besides the HF repos, WhisperX fetches its own models (`large-v3` and the English align model `WAV2VEC2_ASR_LARGE_LV60K_960H`), and `uvx` fetches the whisperx package itself. Where each lands (HF cache, torch cache, uv cache) is **[U]**. `config.yaml` also lists `facebook/dinov2-large` as an image feature, but `features_to_use` is text, audio, video, so it is probably not needed **[U]** | One-time warm-up: point every cache (HF, uv, torch **[U]**) at the volume, run one real clip end to end, list what landed in `MANIFEST.txt`, commit the volume. Normal runs use `HF_HUB_OFFLINE=1` and fail loudly if anything is missing (`the build notes` 5.3). A ~14 GB hub copy added 1 to 2 min to every cold start for techfreakworm | [code] `eventstransforms.py`, `config.yaml`; [3P] techfreakworm (community notes) |
| Text input fails inside a locked-down container | Text goes through gTTS, which needs internet | Not an issue for v1 (video only). Note it if text input is added later | [code] `pyproject.toml` (gtts); [3P] brn-mwai fork (`the build notes` section 7) |

**Llama access steps (you does this once. The decisions note budgets about 15 min of his time for all setup, plus the approval wait)**
1. Log into Hugging Face with your own account.
2. Open `huggingface.co/meta-llama/Llama-3.2-3B`. Fill the short form (name, company, purpose). Bee: "It'll hardly take 2 minutes". Answer truthfully.
3. **Tick the terms and conditions box**, then submit.
4. Wait for the approval email. Reported waits: about 10 min (Bee), about 20 min (Gui em Produção), about 1 hour (Fuzz Puppy). The decisions note says 10 to 60 min. The model page then says you have been granted access (Bisma Majeed video).
5. Settings > Access Tokens > new token, type **Read** (Bee, Fuzz Puppy).
6. Save it as Modal secret `huggingface` (key `HF_TOKEN`) under the **your-modal-profile** profile. Mount it only in the one-time download function (`the build notes` 5.2).


---

## 3. Config and runtime errors

| Symptom | Cause | Fix | Source |
|---|---|---|---|
| `AssertionError: Torch not compiled with CUDA enabled`, or crashes on any CPU or Mac run | `config.yaml` hard-codes `device: cuda` for the feature extractors (4 places). `from_pretrained(device=...)` only moves the main brain model, not the extractors | Run on a Modal GPU, where `cuda` is right. If a step must run on CPU, override the extractor devices through `config_update` (exact keys **[U]**: copy from video-performance-analyzer or amirmushichge, which both rewrite `device: cuda`). PR #9 (open) adds overrides | [code] `config.yaml`, `demo_utils.py`, PR #9; [3P] community notes |
| DataLoader worker crash, "daemonic processes" errors, or a hang | `config.yaml` sets `data.num_workers: 20`. Forked workers break in containers and on ZeroGPU | `TribeModel.from_pretrained(..., config_update={"data": {"num_workers": 0}})`. The nested form copies Square Zero's `config_update={"data": {"features_to_use": ["video"]}}`. Print the loaded config once to confirm it took effect **[U]**. Many tools do this (video-performance-analyzer, amirmushichge, MoburstAI, beta3, antfx) | [code] `config.yaml` line `num_workers: 20`, `from_pretrained(config_update=...)`; [3P] community notes; cerebrum-app logged a DataLoader worker crash |
| Needs a `__main__` guard | DataLoader workers on spawn-based platforms re-import the script | Not needed once `num_workers` is 0 | [3P] Hook-Brain |
| `NameError: CACHE_FOLDER is not defined` in Meta's notebook | `CACHE_FOLDER` is set in the model-loading cell (cell 4 of `tribe_demo.ipynb`). Running a later cell after the forced restart, without re-running that cell, loses it **[U, most likely]** | In the notebook: re-run the loading cell. In our code: always pass `cache_folder=` explicitly, as a path on the volume (Sahu & Pandey use `/cache/tribev2`) | [code] `tribe_demo.ipynb`; [3P] Fuzz Puppy video comments; arXiv 2607.01400 code |
| Run sits at "extracting words from audio" for a long time with no progress | This step shells out to `uvx whisperx ... --model large-v3 --batch_size 16` with output captured, so you see nothing until it ends. The first call also builds the uvx environment and downloads models. WhisperX "takes 2 to 4 min the first time" (beta3). On CPU it is far slower **[U on the exact cause]** | Check `torch.cuda.is_available()` inside the container. Warm WhisperX in the one-time download step. Log timestamps before and after this step. Set a function timeout (30 min proposed, `the build notes` 5.5) so a hang cannot bill forever | [code] `eventstransforms.py`; [3P] Fuzz Puppy video comments, beta3 Space (community notes) |
| WhisperX fails on CPU or Apple: ctranslate2 rejects float16 ("float16 compute type ... not supported", quoted in PR #76) | `compute_type = "float16"` is hard-coded no matter the device (`eventstransforms.py`, lines 107 to 108) | On a Modal GPU, nothing to do. On CPU or MPS, use int8 when the device is not cuda. That is PR #20, **still open and unmerged** on 7 Oct 2026 (also #22 and #58 open, #76 closed unmerged). The fix lives in PR #20 itself (its author's fork Rajkumar2002-Rk/tribev2 is 0 commits ahead, per the gap sweep in community notes block 5); dsteinbach's fork has a similar int8 change | [code] `eventstransforms.py`, PRs #20, #22, #58, #76; [3P] community notes |
| `HFValidationError` from `from_pretrained("facebook/tribev2")` on Windows | The code wraps the repo ID in `Path()` and then `str()`, so `facebook/tribev2` becomes `facebook\tribev2` | Don't run TRIBE on Windows. If you must: pass a local folder holding `config.yaml` + `best.ckpt`, or apply PR #11 or #63 (`.as_posix()`) | [code] `demo_utils.py`, issue #10, PRs #11, #63; [3P] hooked.ai: "backslashes corrupting HuggingFace repo IDs" |
| `NotImplementedError: cannot instantiate 'PosixPath' on your system` on Windows | `config.yaml` was saved on Linux with PosixPath tags | Same answer: Linux only. PR #63 has a patch | [code] PR #63; [3P] hooked.ai |
| No error. Security risk | `from_pretrained` reads `config.yaml` with `yaml.UnsafeLoader`, which can run code embedded in a YAML file. PR #59 proposes a safe loader | Load only Meta's config from our own pinned volume copy. Never point `from_pretrained` at a repo or folder you don't trust | [code] `demo_utils.py`, PR #59 |
| `AttributeError: 'NoneType' object has no attribute 'to_soundarray'` or `KeyError: 'type'` when plotting | `plot_timesteps(..., show_stimuli=True)` assumes audio and word events exist. Silent clips and screen recordings have neither. The model itself copes | Use `show_stimuli=False`, or draw our own peak picture. PR #47 (open) adds guards | [code] issue #46, PR #47 |
| Segfault when rendering the brain on a server | The PyVista backend needs a display | Use `PlotBrainNilearn` (render one timestep; its `plot_timesteps` was reported broken), or start Xvfb and render like recozers | [3P] thecmdrunner/tribev3, recozers (via `the build notes` 5.6) |
| `IndexError: too many indices for array: array is 0-dimensional` from `get_topk_rois` | `.keys()` is not wrapped in `list()` when `hemi` is anything but `"both_separate"` | Use `hemi="both_separate"`, wrap it in `list()`, or use `summarize_by_roi` instead. PR #30 (open) | [code] PR #30 |
| `ValueError: video_path must end with one of [...]` | Accepted video types: `.mp4 .avi .mkv .mov .webm`. Exactly one of `text_path`, `audio_path`, `video_path` is allowed | Re-encode everything to `.mp4` in preprocessing (`the build notes` section 6) | [code] `demo_utils.py` |
| Empty events table from a text file | The temp file was not flushed before the call | `flush()`, `os.fsync()`, `close()` before `get_events_dataframe(text_path=...)`. Not needed in v1 (video only) | [3P] DataCamp |

---

## 4. Inputs that give misleading output (no error shown)

| Symptom | Cause | Fix | Source |
|---|---|---|---|
| Words show up where nobody speaks. The language line spikes during silence | "during those silent parts, Whisper hallucinated dialogue where there should have been none." Those fake word events skewed the predictions. She found this testing against her own fMRI | Show the word list with timestamps in every report. Flag words inside silent stretches (ffmpeg `silencedetect`, `the build notes` section 6). For music-only or no-speech reels, skip the word path: `get_audio_and_text_events(..., audio_only=True)` exists in `demo_utils.py` (issue #46 shows the call). Whether to drop flagged words and re-predict is still open (`the build notes` 15, question 8) | [3P] Anna Behler, LinkedIn, 9 Apr 2026 (community notes); [code] `demo_utils.py` |
| Reels over 60 s: too many output rows and every word counted twice. A 119 s clip gave 239 rows instead of 120. In a 96 s clip, a word at 90 s showed up at 210 s | `ChunkEvents(max_duration=60)` splits long audio, but every chunk points at the same WAV. The full transcript is attached to every chunk and the offset is counted twice. The text feature is summed, so text input doubles. PRs #29 and #81 fix it. **Both open** on 7 Oct 2026 | **v1: cap reels at 60 s** (brainiac trims to 60 s; Sahu & Pandey analysed the first 60 s). Or apply PR #81 (its author says a 119 s clip then gives 120 rows) and re-test. Always check that row count is at most the video's seconds | [code] `demo_utils.py`, PRs #29, #81; [3P] brainiac-public, arXiv 2607.01400 |
| Flat line. Nothing stands out | Clips under about 10 s give flat timelines. DataCamp: inputs under 15 to 30 s show uniformly low activation. The model works in 100 s windows (`duration_trs: 100` in `config.yaml`). Why short clips go flat is **[U]** | Reject under 10 s, warn from 10 to 15 s (`the build notes` section 6). Compare A vs B only at similar lengths (our rule, not from research) | [3P] techfreakworm KNOWN_ISSUES, DataCamp; [code] `config.yaml` |
| Thumbnails or still images give odd or weak results | The model is video-only. Stills must be wrapped as short silent clips (1 to 6 s in the wild), which authors call off-distribution. Square Zero: a static thumbnail is "out-of-distribution". Meta did turn images into static videos in paper section 5.9 | v1 rejects stills. If added later, label the result off-distribution and compare images only with images | [3P] community notes C and F, Square Zero notebook; `the build notes` section 5 |
| Word list is wrong or translated for Hindi or Hinglish speech | WhisperX language defaults to `"english"`. Only English, French, Spanish, Dutch and Chinese are supported. The code says auto-detect is off because it only listens to the first 30 s, "which can be empty e.g. for movies". The effect on predictions is **[U]** | v1: English-speech reels only. For others, use `audio_only=True` and say in the report that the language line is off | [code] `eventstransforms.py` (`ExtractWordsFromAudio`) |
| No hearing or language lines, or a plotting crash | The reel has no audio track or no speech. The model still predicts (trained with modality dropout, p = 0.3; `main.py` drops the text extractor when there are no word events). Plotting is what crashes (see section 3) | Report "no audio" or "no speech" plainly. Don't treat flat lines as a finding | [code] issue #46; `the build notes` section 7 |
| Sharp spikes at cuts to black | Cuts to black make artefact spikes | Detect black frames (ffmpeg `blackdetect`) and skip them when picking peaks | [3P] video-performance-analyzer (via `the build notes` section 6) |

---

## 5. Output mistakes (wrong answers with no error)

| Symptom | Cause | Fix | Source |
|---|---|---|---|
| `preds` has fewer rows than the video has seconds | `remove_empty_segments=True` by default. One-second segments with no events are dropped. `predict` returns `(n_kept_segments, 20484)` | Never assume row i is second i. Use `segments` (the demo says it "contains the corresponding time segments with their associated events") to get each row's time. Save both. Use JSON or `.npy`, not pickle (`the build notes` 5.5) | [code] `demo_utils.py` docstring, `tribe_demo.ipynb` |
| Peaks sit about 5 s away from the cut or word that should cause them | The output is already shifted 5 s back to cancel the blood-flow delay. Shifting it again is a known bug (infi02; Varnan uses `hrf_offset = 5`). Issue #78's lag scan against real fMRI peaked "at exactly 0", which supports no extra shift | No extra shift. Confirm on the first reel with a hard cut or loud sound at a known second (`the build notes` section 6) | [3P] issue #78, community notes (infi02, Varnan); README via `the build notes` |
| Timeline twice as long or squashed | Output is 1 row per second (1 Hz). Nicopotas05 assumed 2 Hz | Treat rows as 1 s steps, then map them with `segments` | [3P] community notes; `the build notes` section 6 |
| "Visual" or "amygdala" scores that mean nothing | Columns are mesh order (left hemisphere first, then right), not brain areas. The main checkpoint is cortex only, so no amygdala or NAcc | Use the real HCP-MMP1 helpers (`get_hcp_labels`, `get_hcp_roi_indices`, `summarize_by_roi`). Don't copy MersivMedia, hmb/tribe2, coygg, DojoCodingLabs | [3P] community notes D; issue #23 |
| A vs B picks the wrong winner | Scaling each clip to its own 0 to 100 erases the difference. Reeled In "called the winner backwards" on a known pair. luckycat210: the strongest region "always lands near 95" | One shared scale for both clips in a comparison | [3P] community notes D |
| Peaks always land near the end of the video | Reported by Josh Wade. His `PEAK_FIX_INSTRUCTIONS.md` names the causes: linear drift, smoothing edge artefacts and duplicate neighbouring peaks (community notes; fix adopted in `SCORING.md` section 12) | If peaks sit at the end on several different reels, suspect a bug before believing it | [3P] community notes (JoshW-dev) |
| Plausible-looking numbers when the model never ran | Some tools fall back to fake output: brainiac `MOCK_MODE`, Javier18888 (random noise), AnshClaude (seeded simulator) | Fail loudly. Never return made-up numbers. Record the tribev2 commit and GPU type in every run's metadata | [3P] community notes (Warning section), community notes |

---

## 6. Hardware and hosting

| Symptom | Cause | Fix | Source |
|---|---|---|---|
| `CUDA out of memory`, or a crash when Llama loads. Issue #28: a Colab T4 with 14.56 GiB total, 13.86 GiB already allocated by PyTorch | The full path is about 28 to 32 GB (V-JEPA2 Giant about 14 GB + Llama about 7 GB + Wav2Vec-BERT about 1 GB). DataCamp: a T4 "will crash during LLaMA initialization". launchpointhq: "24 GB+ ... does not fit in 16 GB". **Conflict:** some tutorials finished the full demo on a free Colab T4 (Bee, Ishii), and Sahu & Pandey ran it unmodified on an A10G (24 GB) | No T4 for the Llama path. Video-only (`features_to_use: ["video"]`) fits a T4 (Fuzz Puppy thumbnail notebook), but it loses the hearing and language lines we need. First test on **L40S (48 GB)**, then the same reel on **A10G (24 GB)**. A100-80GB only as a fallback (`the build notes` 5.4) | [code] issue #28; [3P] DataCamp, launchpointhq, arXiv 2607.01400, Square Zero |
| Run dies mid-batch, or the free GPU quota runs out | Colab sessions disconnect and have usage limits. spike-tribe had to cut 52 videos to the first 30 s after a disconnect. Ifesi needed a keep-alive hack. Commenters hit free-tier limits. Kaggle's free GPUs failed: "it doesn't have enough RAM" | Don't host on Colab or Kaggle. On Modal: one video per GPU call, save `preds` to the volume as soon as each video finishes, set an explicit function timeout | [3P] spike-tribe-validation, ifesiTinkering, Fuzz Puppy comments, Bee video |
| Spaces break after a platform update. `from_pretrained` throws `FileNotFoundError` inside `@spaces.GPU`. V-JEPA2 fails | ZeroGPU narrowed its supported torch to 2.8 to 2.11 (the widely copied beta3 template broke), while tribev2 needs below 2.7. GPU workers seem to have isolated filesystems (the #24 reporter's guess). Neurafeed: "V-JEPA2 video extractor fails on ZeroGPU" | Not our host. Don't port the tool to HF Spaces or ZeroGPU | [code] issue #24; [3P] beta3, Neurafeed (community notes) |
| Hours per video, or out of memory, on a laptop | video-performance-analyzer: 60 s of video takes about 96 min on CPU. V-JEPA2 ViT-g in fp32 needs about 85 GB on Apple Silicon (techfreakworm) | The laptop only runs the skill. TRIBE runs on Modal | [3P] community notes F, techfreakworm |
| HTTP request times out while TRIBE is still running | Runs take minutes. Advolve: batching several creatives into one request "exceeded gateway timeouts". NeuroPitch: stuck GPU jobs deadlocked its WebSocket | Submit-then-poll job API (`the build notes` 5.7). One stimulus per GPU call with bounded concurrency. Modal's web endpoint size and time limits are not in the research **[U, check Modal docs]** | [3P] Advolve (Devpost), NeuroPitch Space (community notes) |
| Another function can't see files the GPU function wrote | Modal Volumes need a commit after writes and a reload before reads in other containers **[U, check current Modal docs]** | Commit after saving `preds`. Reload before reading | `the build notes` 5.2 |
| GPU bill higher than the work done | The GPU sits idle about 44% of each call during CPU prep (techfreakworm) | Do ffmpeg prep and plotting on CPU functions. The GPU function only predicts and returns (the pattern in recozers' code comments) | [3P] techfreakworm, recozers/tribe-inference |
| A reel link fails to download | YouTube: yt-dlp is blocked by SABR streaming (Sahu & Pandey). Instagram: refused an anonymous yt-dlp download ("rate-limit reached or login required", seen 8 Oct 2026). We never log in or use cookies (project rule) | `tribe.ps1 reel <link>` tries yt-dlp with no cookies. For a public Instagram reel it then uses Apify `apify~instagram-scraper` with `APIFY_TOKEN` . Private, deleted or non-video posts still fail, so save the file and pass the path | [3P] arXiv 2607.01400; seen 8 Oct 2026; project `CLAUDE.md` |

---

## 7. Money, accounts and licence

| Symptom | Cause | Fix | Source |
|---|---|---|---|
| A huge Modal bill | "My Modal GPU bill hit $500 in the last three days running the A100" (a public-site builder). He did not say why. His site was public and multi-user. Likely culprits **[U]**: warm containers, long idle windows (advaitpaliwal uses a 10 min `scaledown_window`), parallel GPU containers, no timeout | Before the first deploy: hard monthly cap in code (`MONTHLY_BUDGET_CAP_USD`, the name brainiac-public uses with a default of 300; `the build notes` 11 suggests $20 to $30 for the test month). Refuse runs at or over the cap. Keep-warm off. Short idle window. Max one GPU container. 30 min function timeout. 60 s max video. Check whether Modal has a workspace spend limit and turn it on **[U]**. Compare the ledger with Modal's billing page every month | [3P] issue #25; brainiac-public, advaitpaliwal (community notes); `the build notes` D12 |
| Runs billed to the wrong Modal workspace | The active Modal profile on your machine is not the account you meant to bill | `modal profile activate your-modal-profile` before any deploy or run, then confirm which profile is active with `modal profile current` (the command in `.env.example` and `the build notes` D4; **[U: confirm with `modal profile --help`]**). Never deploy from another Modal account | community notes; `the build notes` D4 |
| Licence trouble from hosting it for others | TRIBE v2 is CC BY-NC 4.0. Meta reportedly is "not planning to offer any kind of commercial license" (relayed, #25; #17). A public-site builder decided "even hosting the model so users can do their research is inappropriate since it's for more than one user" and took his site down | Free, credited to Meta, no upsell, never a lead magnet for paid work. Skill first (private), site later. Not legal advice | [3P] issues #17, #25; `the build notes` D7 |
| HF token or API keys leak | Keys pasted into code or committed | Keys live only in `.env` (never committed) and in Modal secrets. The HF secret is mounted only in the download function | Project `CLAUDE.md`; `the build notes` 5.2 |

---

## 8. Conflicts with the other docs (fix them there)

Found while checking Meta's code on 7 Oct 2026. This file does not edit the other docs.

**Status (verifier pass, 7 Oct 2026):** the first three rows are now fixed. `the build notes` 5.1 uses numpy 2.2.6 and names exca 0.5.26 as the NoValue cause, and `the build notes` sections 6, 11, 12 and 15 plus `COSTS-AND-TIMES.md` 8.6 now cap reels at 60 s. The fourth row was about the task brief, not a doc.

| Topic | Other doc says | This file says | Why |
|---|---|---|---|
| numpy pin | `the build notes` 5.1: `>=1.26.4,<2.1.0`, installed first | numpy 2.2.6 + scipy 1.15.3 | tribev2 `pyproject.toml` hard-pins `numpy==2.2.6` [code]. Square Zero's 1 Oct 2026 working set uses 2.2.6 + 1.15.3. `the build notes` section 3 already flags this |
| Max video length | `the build notes` section 6 and 11: 90 s | 60 s until PR #29/#81 is merged or patched in | Audio over 60 s duplicates words and shifts their times [code] |
| Cause of the `NoValue` error | `the build notes` 5.1 blames Python 3.12 | exca 0.5.26 is the cause. `pyproject.toml` now pins 0.5.20 | Issue #65 text. Python 3.11 is still the safe pick |
| "Meta notebook pins numpy 2.2.6 / scipy 1.15.3 / torch 2.6.0" | Task brief | Meta's notebook pins nothing. Those pins are in the Square-Zero-Labs notebooks | Both notebooks read on 7 Oct 2026 |

---

## 8b. Found while building M1 (8 Oct 2026; fixed in `backend/`)

Read from upstream code (tribev2 af58661, neuralset 0.0.2, exca 0.5.20, whisperx 3.8.6) and the modal 1.3.2 client, or reproduced on your machine.

| Symptom | Cause | Fix (built) |
|---|---|---|
| Every cold start re-downloads about 400 MB, or offline runs fail in `AddText` | neuralset's `get_spacy_model('english')` pip-installs `en_core_web_lg` at run time if it is missing | Bake the `en_core_web_lg` 3.8.0 wheel into the image |
| WhisperX version drifts or needs network | tribev2 calls an unpinned `uvx whisperx`. whisperx 3.8.x needs torch ~2.8 and huggingface-hub<1.0, so it cannot share tribev2's env | `uv tool install whisperx==3.8.6` at build time (`UV_TOOL_DIR=/opt/uv/tools`), plus a `uvx` shim first on PATH that sends `uvx whisperx ...` straight to that install. Without the shim, uvx re-resolves `whisperx` from the index and fails with the network blocked ("whisperx was not found in the cache", seen on Modal 8 Oct 2026). Bake NLTK `punkt_tab` too |
| A new clip silently returns the previous clip's transcript or features | `clip.wav` and `clip.tsv` are written next to the input and reused if present. exca feature caches are keyed by file path and offset, not content | Give every job a unique folder (`jobs/<timestamp>-<sha8>/clip.mp4`) and keep the feature cache in container `/tmp` |
| `from_pretrained("facebook/tribev2")` takes whatever is on HF main | It calls `hf_hub_download` with no revision | Download `config.yaml` and `best.ckpt` at revision f894e78 into `/weights/tribev2` and load from that local folder |
| Segments can't be saved | neuralset `Segment` objects fail to unpickle outside their dataset | Write `segments.json` by hand: start, stop and words per row |
| iPhone HDR clips look washed out to V-JEPA2 | 10-bit HLG or PQ BT.2020 cut to 8-bit with no tone-mapping | Tone-map with zscale + tonemap (hable) to BT.709 when `color_transfer` is HLG or PQ. Flagged as `hdr_input` |
| Browser and screen-recorder WebM rejected as a "still image" | No Duration element, so ffprobe reports no duration | Fall back to scanning the packets for the duration |
| Re-encoded clip shows one still frame | Cover art stream listed before the real video, and `-map 0:v:0` picks it | Map the exact stream index that was checked |
| Silence or black ranges inverted or shifted | ffmpeg prints times with `%.6g` (`-0.0213`, `2.08e-05`) | Parse signed numbers and exponents, and pair each start with the end that follows it |
| `tribe.ps1 reel <file>` fails with "Option '--label' requires an argument" | Windows PowerShell 5.1 drops empty-string arguments to native programs | Pass `--label` only when it has a value |
| `modal run` crashes with UnicodeEncodeError when its output is piped | This laptop's console is cp1252, and modal prints the U+2713 tick | `tribe.ps1` sets `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` |
| A timed-out job prints "still running" forever | Modal's `FunctionTimeoutError` subclasses `modal.exception.TimeoutError`, and the poll loop caught it as "not ready yet" | Catch only Python's built-in `TimeoutError` as "still running". Modal timeouts end the run with a clear message |
| `modal profile list` signs in as another Modal account | It looks up the workspace for every saved profile | The launcher uses `modal token info`, which uses only the active profile |
| `Please add a payment method to use A10G GPU functions.` when running any step, even a CPU-only one | Modal won't create an app that contains a GPU function until the workspace has a payment method, even on the Starter plan's free credit (seen 8 Oct 2026) | Add a card in the Modal dashboard before the first GPU run, with the workspace budget at $30 . Meanwhile `tribe.ps1 smoke` and `weights` set `TRIBE_CPU_ONLY=1`, which leaves the GPU class out of the app |
| Modal web requests cut off | A web endpoint request can run for at most 150 s, then Modal returns a 303 to a result URL | M4 endpoint: submit, then poll (fills the [U] in section 6) |

## 9. First-run checklist

**A. Before any code runs**
- [ ] `modal profile activate your-modal-profile`, then confirm with `modal profile current`. Never another Modal account.
- [ ] you picks the monthly cap and writes it to `.env` as `MONTHLY_BUDGET_CAP_USD`. The code refuses runs at or over it.
- [ ] Look up Modal GPU prices on modal.com/pricing (not in the research) and fill the rate table.
- [ ] Check the Modal dashboard for a workspace spend limit. Turn it on if it exists.
- [ ] Llama 3.2 3B access granted (steps in section 2, terms box ticked). Read token saved as Modal secret `huggingface`.

**B. Build the image**
- [ ] Linux image, Python 3.11, apt `ffmpeg` and `git` (plus `xvfb` only if rendering with PyVista).
- [ ] tribev2 from git at a pinned commit. Main was `af58661` (23 Jun 2026) when checked on 7 Oct 2026.
- [ ] Pins: numpy 2.2.6, scipy 1.15.3, torch 2.6.0, torchvision 0.21.0, torchaudio 2.6.0, exca 0.5.20, plus `uv`. No pip-installed whisperx.
- [ ] (Built 8 Oct 2026) WhisperX 3.8.6 pre-installed with `uv tool install` so the unpinned upstream `uvx whisperx` runs a fixed version offline. Bake the spaCy `en_core_web_lg` model and NLTK `punkt_tab` into the image: neuralset's `AddText` otherwise pip-installs `en_core_web_lg` (about 400 MB) at run time on every cold start, and WhisperX downloads `punkt_tab`. Run `backend/tribe.ps1 smoke` to check all of this.
- [ ] Smoke test in the image: `from tribev2.demo_utils import TribeModel`, print numpy, scipy, torch, exca versions, and run one small scipy call (Square Zero's notebook does this check).

**C. One-time weight download**
- [ ] `HF_HUB_DOWNLOAD_TIMEOUT=300`. HF, uv and torch caches all on the `tribe-weights` volume.
- [ ] Run one real clip end to end (Meta's demo uses the Sintel trailer) so WhisperX and its align model land in the volume.
- [ ] Write `MANIFEST.txt` (names and sizes). Commit the volume.
- [ ] Normal runs: `HF_HUB_OFFLINE=1`, HF secret not mounted.

**D. Settings in code**
- [ ] `config_update={"data": {"num_workers": 0}}`. Print the config once to confirm.
- [ ] `cache_folder=` set explicitly to a volume path.
- [ ] Plot with `show_stimuli=False` or our own picture, on a headless backend.
- [ ] Function timeout 30 min. Keep-warm off. Short idle window. Max one GPU container.
- [ ] Reject stills, clips under 10 s, and clips over 60 s. Re-encode to `.mp4`.
- [ ] No mock fallback anywhere. Errors fail loudly.

**E. The first real reel**
- [ ] Pick an English-speech reel, 15 to 60 s long, with a hard cut or loud sound at a known second and at least one silent stretch.
- [ ] Run it on A10G first , and on L40S only if A10G runs out of memory. Record: fits in memory, cold start time, GPU seconds for `get_events_dataframe` vs `predict`, total estimated USD (`the build notes` section 14). `predict_meta.json` holds these.
- [ ] Check `preds.shape`: second number is 20484, row count is at most the reel's seconds. Map rows to time with `segments`.
- [ ] Read the word list: any words inside silent stretches? Are the words right?
- [ ] Check timing: the response moves near the known cut with no extra shift.
- [ ] Check nothing was downloaded (offline mode passed).
- [ ] Check it's real output: values change over time, and a second, different reel gives a different curve.
- [ ] If A10G ran out of memory, run the same reel on L40S and compare time and cost.
- [ ] Freeze the working package list (`pip freeze`) and record the time and cost per reel in `the build notes` and `the build notes`.
- [ ] Set the real monthly cap from the measured cost.

---

## Sources

**Read directly on 7 Oct 2026 [code]**
- https://github.com/facebookresearch/tribev2 at commit `af58661`: `pyproject.toml`, `tribev2/demo_utils.py`, `tribev2/eventstransforms.py`, `tribe_demo.ipynb`
- https://huggingface.co/facebook/tribev2/blob/main/config.yaml
- Issues #2, #6, #10, #17, #23, #24, #25, #27, #28, #46, #65, #69, #78 and PRs #9, #11, #20, #22, #29, #30, #47, #56, #58, #59, #63, #67, #76, #81
- https://github.com/Square-Zero-Labs/tribev2 (`tribe_demo.ipynb`, `tribe_thumbnail_study.ipynb`, install cells)

**Project research (untrusted data, summarised)**

**Other docs in this folder**
