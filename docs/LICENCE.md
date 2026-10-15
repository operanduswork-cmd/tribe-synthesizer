# Licence and credit notes

This project runs TRIBE v2 by Meta FAIR, which is licensed CC BY-NC 4.0. That means non-commercial use only. This is not legal advice. Re-read the licence texts yourself before you share anything.

## Who owns what

| Part | Licence |
|---|---|
| Our code (this repo) | MIT, see `LICENSE` |
| TRIBE v2 weights and code (Meta FAIR) | CC BY-NC 4.0, https://creativecommons.org/licenses/by-nc/4.0/ |
| Llama 3.2 3B (text path) | Llama 3.2 Community License, gated on Hugging Face |
| Outputs made with TRIBE v2 | Treat as non-commercial too |
| Third-party libraries | Their own licences, listed in `LICENSES/CREDITS.md` |

The whole project, as a working tool, is for non-commercial use. The MIT licence on our code does not lift the CC BY-NC limit on the model.

## Allowed and not allowed

Allowed: personal use, learning, research, free non-commercial sharing with credit.

Not allowed: selling access or scores, paid tiers, cost recovery, client work, paid deliverables, using the tool to win clients, or gating it behind a sign-up, email or comment.

Commercial use needs Meta's permission (research-licensing@meta.com).

## Official Llama access only

Request access to `meta-llama/Llama-3.2-3B` on Hugging Face yourself. Do not use ungated re-uploads or mirrors.

## Texts to show

### A. Web page footer (every page)

```
Built on TRIBE v2 by Meta FAIR, licensed CC BY-NC 4.0 (non-commercial). Built with Llama. Free, not affiliated with Meta. Shows a predicted average-brain response, not a view forecast.
```

Link "TRIBE v2" to https://github.com/facebookresearch/tribev2, "CC BY-NC 4.0" to https://creativecommons.org/licenses/by-nc/4.0/ and "Built with Llama" to the Llama licence.

### B. About and licence block

```
About this tool

This is a free, non-commercial research tool.

It runs TRIBE v2, a brain-response model made by Meta FAIR (d'Ascoli et al., 2026).
TRIBE v2 is licensed under CC BY-NC 4.0: https://creativecommons.org/licenses/by-nc/4.0/
Model: https://huggingface.co/facebook/tribev2
Code: https://github.com/facebookresearch/tribev2
We use the released weights without changes.

Built with Llama. The text path uses Llama 3.2 3B. Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved.

This tool is not made, endorsed or supported by Meta.

What you get: a predicted response of an average brain, second by second. It is not your audience. It does not predict views, reach or virality.

It is free. There is no paid tier, no sign-up and no email list. Please don't use the results in paid or client work. The model's licence does not allow it.

Only upload videos you have the right to use. Not medical advice.
```

### C. Report footer (offline pages)

```
Predicted average-brain response from TRIBE v2 (Meta FAIR, CC BY-NC 4.0). Built with Llama. Non-commercial use only. Not a view forecast.
```

### E. Report footer (the offline pages and the `/reel` and `/script` skills)

```
Predicted average-brain response from TRIBE v2 (Meta FAIR, CC BY-NC 4.0). Built with Llama. Non-commercial use only. Not a view forecast.
```

## Checklist before you share anything publicly

Public means a web page anyone can reach, a public repo, or sharing the tool with others.

Licence texts
- [ ] Re-read the CC BY-NC 4.0 legal code and the LICENSE in the tribev2 GitHub repo and on the Hugging Face model page.
- [ ] Read the Llama 3.2 Community License and Acceptable Use Policy. Add a copy to `LICENSES/`.
- [ ] Check the licences of V-JEPA 2, Wav2Vec-BERT, WhisperX and any other model you add.

Clean inputs
- [ ] Llama access came through the official form.
- [ ] No ungated mirror appears anywhere in the code.
- [ ] Weights live only in your private Modal volume. No public weight download.

No money, no leads
- [ ] No payment code, paid tier, tip jar, donation link or cost recovery.
- [ ] No email capture, sign-up wall, comment-to-unlock or DM gate.
- [ ] No link to paid services on the page, README or output.

Credit and wording
- [ ] Footer A on every page, block B reachable from every page.
- [ ] Output ends with text C.
- [ ] No UI copy claims views, virality or a forecast. "Not affiliated with Meta" is visible. No Meta logo.

Safety rails
- [ ] Monthly spend cap set and tested: new runs are refused once the cap is hit.
- [ ] Upload terms and a deletion rule written. No gallery of other people's videos.
- [ ] You collect no one else's data. Keep scraped creator data out of any public repo.
