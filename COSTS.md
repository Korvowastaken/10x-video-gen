# Costs: measured latency, GPU time and list-price equivalents

All numbers come from `runs.jsonl` (149 model calls on 2026-11-25, `make
costs`). Free tiers cost us nothing; "list price" is what the same calls would
cost at each provider's published paid rate.

> **Which log.** The runs below were made while building the pipeline on the
> brief's placeholder story, on 2026-11-25. When the real story replaced it,
> `runs.jsonl` started again for the new film, so the placeholder run's log is
> kept as `logs/placeholder-runs.jsonl` (173 calls; its first 149 are the ones
> counted here). Where an entry below says `runs.jsonl`, it means that file.

## What the free tiers actually allowed (2026-11-25)

| Provider | The brief said | We found |
|---|---|---|
| Gemini API (free tier) | free, Amharic TTS included | Works, but small daily quotas per model. `gemini-3.8-flash-tts` stops at **10 requests a day** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 10`), and so does 3.8 Flash Lite TTS. 3.8 and 3.7 Flash ran out after a handful of calls; 3.5 Flash carried every script draft. Frequent 503 "high demand". |
| Cloudflare Workers AI | roughly 50-170 images a day | 10,000 neurons a day. FLUX.2 klein 4B at 768×1344 costs about 157 neurons, plus about 32 per reference image (measured: 231.6 neurons for an end keyframe with 3 references). That is about 40 keyframes a day with references, or about 95 without. |
| Kaggle | about 30 GPU hours a week | **6 hours a week** on this account (`totalTimeAllowed: 21600s`, refresh Saturday). We moved video and music off Kaggle (FAILURES F12). |
| WaveSpeed AI (added) | not in the brief | Pay per use. New accounts "may receive" $1 of trial credit (eligibility not guaranteed). |

## Measured latency per call (median)

| Stage | Model | Calls (ok) | Median | Max |
|---|---|---|---|---|
| script | gemini-3.5-flash, one storyboard draft | 6 | 54.1 s | 67.9 s |
| keyframes | FLUX.2 klein 4B, 768×1344, up to 4 references | 24 | 11.2 s | 19.4 s |
| narration | gemini-3.8-flash-tts, one line | 13 | 9.2 s | 29.5 s |
| narration | gemini-3.8-flash-lite-tts, one line | 11 | 4.8 s | 12.7 s |
| narration | gemini-3.5-transcribe, listen-back | 24 | 21.2 s | 60.1 s |
| shots | gemini-3.5-flash-lite, finding a mask | 2 | 3.9 s | 5.0 s |
| shots | WaveSpeed Wan 2.2 I2V 480p, 5 s clip (submit to download) | 1 | 55.5 s (34.3 s of it inference) | |
| music | WaveSpeed ACE-Step 1.5, 10 s track | 1 | 11.8 s | |
| smoke | Kaggle GPU job, push to results | 1 | 65.1 s (8.6 s on the GPU) | |

Local steps on the laptop (Intel i7-8650U, UHD 620, no NVIDIA GPU):

| Step | Measured |
|---|---|
| Depth map (Depth Anything V2 Small, int8 ONNX, CPU) | 9 keyframes in 52 s including model load |
| Parallax render, 4 s at 540×960 | 2.3 s |
| Masked composite (alignment, colour match, feathered blend), 161-frame clip into a 320-frame loop | 43 s |
| RIFE v4.25 on the UHD 620 (Vulkan) | 278 ms per synthesised frame at 464×832; 0 frames needed at the 1.25x cap |
| Radio cut assembly, 11 shots | 43 to 63 s |

## Calls and errors per stage

| Stage | Calls | OK | Errors | Total latency (s) | GPU (min) | Neurons | List price (USD) |
|---|---|---|---|---|---|---|---|
| keyframes | 24 | 24 | 0 | 293.9 | 0.0 | 4,081 | 0.045 |
| narration | 62 | 49 | 13 | 919.8 | 0.0 | 0 | 0.062 |
| script | 31 | 6 | 25 | 746.5 | 0.0 | 0 | 0.158* |
| shots | 17 | 3 | 14 | 112.2 | 0.6 | 0 | 0.051 |
| smoke | 15 | 7 | 8 | 310.2 | 0.2 | 69 | 0.018 |

\* 3.5 Flash has no row on Google's pricing page; it is priced like 3.8 Flash
($0.75 in, $3.75 out per million tokens), so this line is an estimate.

The errors are the honest part of the log: Gemini 503s and daily quotas
(script, narration, mask lookups), each retried or routed down a fallback
chain, and each one a line in `runs.jsonl`.

**Spent so far:** $0.053 at WaveSpeed (one $0.05 test clip, one $0.003 music
test). Everything else ran on free tiers.

## One shot in detail: S03, the only moving clip so far

S03 ("the mother reaches out, the girl steps across the stream") is an
`flf_inbetween` shot: a clear start state and a clear end state. It was the
test for whether WaveSpeed's `last_image` pins the final frame (it does,
EXPERIMENTS E7), and the only clip bought so far. The other six paid shots were
left unbought on purpose and fell back to parallax in the test film.

How it was made:
1. **Start frame:** the S03 keyframe, with the mother reaching out.
2. **End frame (S03_end):** drawn with the start frame as a reference, so only
   the pose changes (now holding hands).
3. **Clip:** Wan 2.2 got both frames and generated the 5 s movement between them.

| Part | Service | Paid | List price |
|---|---|---|---|
| Moving clip, 5 s at 480p | WaveSpeed Wan 2.2 I2V Ultra Fast | $0.05 | $0.05 |
| Start keyframe | Cloudflare FLUX.2 klein (free allowance) | $0 | ≈ $0.0025 |
| End keyframe (232 neurons) | Cloudflare FLUX.2 klein (free allowance) | $0 | ≈ $0.0025 |
| Depth map, RIFE retiming, edit | laptop | $0 | – |
| **Total** | | **$0.05** | **≈ $0.055** |

The clip took 55 s from request to download, 34 s of it generation. The
character reference sheets are shared by every shot and are not counted here.
The six remaining paid shots add about $0.33 (five at $0.05, S06 at $0.08).

## What one film costs at list price (balanced plan)

| Item | Count | List price |
|---|---|---|
| Paid clips, WaveSpeed Wan 2.2 480p | 6 × 5 s + 1 × 8 s | $0.38 (about $0.51 with retries) |
| Score candidates, ACE-Step 1.5, about 80 s each | 3 | $0.07 |
| Keyframes + references, FLUX.2 klein | about 25 | $0.06 at $0.011 per 1,000 neurons (free under the daily allowance) |
| Script drafts, Gemini Flash | 1 to 3 | about $0.05 |
| Narration, 3.8 Flash TTS + listen-back | about 12 lines | under $0.05 |
| **Total** | | **about $0.60 per film, about $0.45 of it actually paid** |

Against "every shot full image-to-video, length-matched", which comes to
$1.14 with retries (research/motion-on-a-budget.md), the balanced plan pays
for 7 clips instead of 11 and fills the rest with free local motion. On $1 of
credit, that is about 2 films instead of about 1.

## Rates used (read on 2026-11-25)

- **Gemini** (aistudio.google.com/docs/pricing, standard tier, prices "through December 31, 2026"), per million tokens:
  - 3.8 Flash: $0.75 in, $3.75 out (verbatim).
  - 3.5 Flash-Lite: $0.30 in, $2.50 out (verbatim).
  - 3.5 Transcribe: $2.00 audio in, $12.00 out (verbatim).
  - 3.8 Flash TTS: $0.50 in, $9.00 audio out. 3.8 Flash Lite TTS: $6.00 audio out. Both read from a summarised part of the page, so treat them as approximate. Audio counts as 25 tokens a second.
- **Cloudflare** (pricing page modified 2026-11-18):
  - FLUX.2 klein 4B: $0.000287 per output 512×512 tile, $0.000059 per input tile.
  - FLUX.1 schnell: $0.0000528 per tile, $0.0001056 per step.
  - $0.011 per 1,000 neurons above the free 10,000 a day.
- **WaveSpeed** (model pages):
  - Wan 2.2 I2V 480p Ultra Fast: $0.05 per 5 s, $0.08 per 8 s.
  - 720p: $0.10 and $0.16.
  - ACE-Step 1.5: $0.0003 a second.
  - The pages warn that "the final task charge prevails".
- **Kaggle T4**: no price exists for the free quota. `make costs` values an hour of "GPU T4 x2" at $0.70, an estimate from about $0.35 an hour per on-demand T4.

## Frontier comparison

We had no access to the frontier lane (no organisation key for Omni Flash,
Nano Banana or Lyria 3.5), so there is no measured frontier comparison. The
research note lists hosted alternatives and their prices for the same motion
jobs (Wan VACE masked video $0.30 per 5 s, Kling motion brush about $0.225,
Kling start-end $0.45), all 4 to 9 times the $0.05 clip we use.
