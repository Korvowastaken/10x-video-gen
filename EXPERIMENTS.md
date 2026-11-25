# Experiments: hypothesis, change, result

Every number here comes from `runs.jsonl`, a manifest under `outputs/`, or a
measurement script run on the files. Each entry says where. All on 2026-11-25.
`outputs/` is git-ignored (it is rebuilt by `make film`), so the numbers are
copied here; `runs.jsonl` is committed and holds every model call.

## E1. Can every provider be reached on a free tier from here?

- **Hypothesis:** the brief's stack works without a card.
- **Change:** `make smoke GPU=1` calls each provider once.
- **Result:** all three work, with two surprises.
  - Gemini 3.8 Flash answered only after two 503 retries.
  - 3.8 Flash TTS spoke a test line.
  - FLUX.2 klein drew a 512×512 image in 6.4 s.
  - A Kaggle job ran on 2× T4 with internet, 39 s from push to results.
  - Surprise one: Kaggle's quota is 6 h a week, not 30 (FAILURES F4).
  - Surprise two: FLUX.1 schnell takes no seed (F2).
- **Decision:** keep the smoke test as step one of setup, and keep FLUX.2 klein as the main image model.

## E2. Does the script stage produce a valid storyboard without a human fixing JSON?

- **Hypothesis:** with the schema in the prompt and errors fed back, a valid storyboard arrives within 3 attempts.
- **Result:**
  - Run 1: a valid draft on the first attempt, but it contained Burmese letters, which no rule checked for yet (F5).
  - Run 2 (with the script check): draft 1 was rejected, draft 3 accepted (11 shots, 94 words).
  - Run 3 (with the measured speech rate): draft 1 had one problem, then accepted (11 shots, 46 words).
  - Every run fell back from 3.8 and 3.7 Flash to 3.5 Flash (503 or daily quota).
- **Evidence:** `outputs/script/storyboard__*.json`, `runs.jsonl` stage `script`.
- **Decision:** keep the validate-and-repair loop, and keep growing the rules when a model finds a new way to be wrong.

## E3. How fast does Gemini TTS speak Amharic?

- **Hypothesis:** about 2 words a second (the brief's figure for speech in general).
- **First measurement:** 94 words gave 97 s of speech, which looked like 1.0 words a second. We cut the script stage's word budget to match.
- **Second look:** the next cut, with half the words, was longer still (131 s). The takes were polluted (E4).
- **Clean measurement:** the bare 4-word line `ዛሬ እሑድ ቡና ታፈላለች።` took 2.25 s, about 1.8 words a second including edge padding.
- **Decision:** the script stage budgets 1.6 words a second for Amharic. The lesson is to measure on takes you have listened to (or checked), because a wrong measurement looks just as precise as a right one.

## E4. Where should the delivery note go?

- **Hypothesis:** a short English note before the Amharic line ("warm, elderly") steers the voice, as Gemini's docs show for English.
- **Results by format:**

| Format | Result |
|---|---|
| `<note>:\n<line>` | S10 transcript was the note itself, in English (CER 2.44) |
| `Say this line in Amharic, <note>, at a natural speaking pace: "<line>"` | Every line 4 to 5 times too long; in 2-second pieces, S08 contains "nostalgic at a" and Amharic words that are not in the script |
| the bare line | 2.25 s for 4 words, clean |

- **Decision:** send the bare line and choose the voice for character. A system-instruction variant is untested, blocked by the daily quota.

## E5. Does a listen-back check catch bad takes?

- **Hypothesis:** transcribing each take and scoring it against the script (character error rate) flags wrong takes automatically.
- **Result:** it caught format 1's spoken note (CER 2.44, re-taken; the closest take was kept). It missed format 2's spoken note (CER 0.08 on a 10 s take of a 4-word line), because the transcriber picked out the line and dropped the rest.
- **Decision:** keep the CER check and add a length check (`narration.too_long`). Two cheap checks that fail differently beat one.

## E6. Do reference images hold a scene between a start and an end frame?

- **Hypothesis:** FLUX.2 klein, given the start keyframe as its first reference, draws an end frame with the same scene and characters, only re-posed.
- **Result:** S03's end frame kept the trees, bridge, light and both characters, with the pose changed from a hand reaching out to holding hands. Mean absolute difference between the two stills: 10.8 (on a blurred 120×208 copy). That is low enough to read as one scene, and high enough for the pose change to show.
- **Evidence:** `outputs/keyframes/contact_sheet.jpg`.
- **Decision:** generate the end frames of in-between shots this way.

## E7. Does WaveSpeed's `last_image` really pin the last frame?

The test the research asked for before building on it.

- **Change:** one `flf_inbetween` clip for S03 ($0.05).
- **Result:**

| Comparison | Mean abs. difference |
|---|---|
| clip's first frame vs start keyframe | 5.14 |
| clip's first frame vs end keyframe | 13.83 |
| clip's last frame vs end keyframe | **3.52** |
| clip's last frame vs start keyframe | 11.2 |
| the two keyframes | 10.76 |

  Visually, the clip starts with the mother reaching out, has her bend to the girl, and ends on the end keyframe's pose.
- **Cost:** 55 s wall, 34 s inference.
- **Decision:** use `flf_inbetween` wherever a shot has a clear start and end state.

## E8. What does WaveSpeed's ultra-fast Wan return?

- **Hypothesis (from research):** 16 fps, so every clip needs RIFE to reach 24 fps.
- **Result:** 464×832 at **30 fps**, 161 frames, 5.37 s.
- **Consequence:** at the 1.25x character cap, 30 / (24 × 1.25) = 1 source frame per output frame, so 0 frames need synthesising. RIFE only works at the 1.6x ambient cap (E9).
- **Decision:** keep RIFE in the chain but stop treating it as mandatory.

## E9. How expensive is RIFE on this laptop?

- **Change:** retime S03's clip with RIFE v4.25 (rife-ncnn-vulkan).
- **Result:**
  - RIFE runs on the Intel UHD 620 through Vulkan. Start-up took 68 s the first time, including the model download.
  - At 1.25x: 161 output frames, 0 synthesised.
  - At 1.6x: 206 output frames, 198 synthesised in 55 s (278 ms each).
- **Decision:** affordable for the few ambient shots that need it.

## E10. Does masked compositing keep the background still?

- **Change:** take S03's clip, have Gemini box "the mother and the girl holding hands" (2 regions, 18% of the frame), then composite with alignment, colour matching and a feathered mask as a ping-pong loop.
- **Result:** 0.0% of the changed pixels lie outside the mask. The background stays exactly the still. 320-frame loop cycle in 43 s on CPU.
- **Decision:** masked_i2v and cinemagraph shots use this, so a weak background in a clip costs nothing.

## E11. Is depth parallax cheap enough to use freely?

- **Change:** Depth Anything V2 Small (int8 ONNX, 27 MB) gives a depth map; `cv2.remap` moves a virtual camera over it.
- **Result:** a 4 s push-in at 540×960 rendered in 2.3 s on CPU.
- **Decision:** parallax is the default for establishing shots and the first fallback for every paid shot.

## E12. Can ACE-Step on WaveSpeed make an instrumental underscore?

- **Change:** one 10 s call with the storyboard's tags plus tempo, key and metre.
- **Result:**
  - A 10 s MP3 in 11.8 s at −19 LUFS, about $0.003.
  - Two API surprises along the way: lyrics are required (F14), and there are no tempo or key fields (F13).
- **Still to do:** how it sounds under the narration needs a human ear.

## E13. How many paid clips does a film need?

- **Hypothesis (research):** making all 11 shots full image-to-video costs about $1.14 with retries. The "balanced" plan does it for about $0.51.
- **Change:** apply the balanced plan to `storyboard.json`:

| Shots | Mode | Paid |
|---|---|---|
| S02, S06 (8 s) | `full_i2v` | yes |
| S03 | `flf_inbetween` | yes |
| S04, S08, S10 | `masked_i2v` | yes |
| S09 | `cinemagraph` | yes |
| S01, S11 | `parallax` | free |
| S05, S07 | Ken Burns | free |

- **Result:** 7 paid clips, $0.38 at list price. `video.max_paid_clips` (7) and `video.budget_usd` ($0.60) stop a run from spending more. Anything over the limit falls back, and the log says which shot fell back.
- **Status:** one of the seven bought (E7). The rest wait for the real story.

## E14. Does one colour grade make the scenes look like one film?

- **Hypothesis:** each keyframe is drawn on its own, so scenes drift in warmth and brightness. Moving every scene part of the way toward the film's median look evens that out without flattening the scenes.
- **Change:** `pipeline/grade.py`. The film's look is the median Lab mean and spread of the 11 current keyframes. Each scene gets a 33³ `.cube` LUT that shifts its Lab mean and spread toward that look (spread ratio clamped to 0.7–1.4, blended by `edit.grade_strength`). Assembly applies it with FFmpeg's `lut3d` to every frame of the scene's segment; the LUT's hash is in the segment's cache key. Measured with `grade.measure(project)`. Distance is the mean per-channel Bhattacharyya distance of Lab histograms (0 same colours, 1 none shared).
- **Result:** on the 11 keyframes, S01–S11 in order:

| | Before | Strength 0.6 | Strength 1.0 |
|---|---|---|---|
| Neighbouring scenes, mean distance | 0.186 | 0.130 | 0.118 |
| Neighbouring scenes, max distance | 0.312 | 0.241 | 0.214 |
| Spread of scene means, L / a / b (std) | 2.77 / 2.83 / 2.01 | 1.11 / 1.11 / 0.80 | 0.02 / 0.04 / 0.02 |

  - A before/after strip of all 11 stills shows no muddy or tinted scenes at 0.6; the interiors lose a little of their blue cast.
  - FFmpeg's `lut3d` and the numpy path used for the measurement agree within 0.5 levels of 255.
- **Decision:** grade every cut except the radio cut, at strength 0.6. It gets most of the gain (0.186 to 0.130) and leaves each scene some of its own light; 1.0 makes every scene's averages identical. `edit.grade: false` turns it off, and `edit.grade: {"target": ...}` fixes the look.
