# Failures: what broke, what we tried, what fixed it

Newest problems are at the bottom. "Evidence" points at the file or log lines
that show it. Times are UTC, as in `runs.jsonl`.

## F1. Gemini 3.8 Flash: "high demand" on the very first call

- **What broke:** the smoke test's first text call got HTTP 503 "This model is currently experiencing high demand" four times in a row.
- **Tried:** waiting, retrying.
- **Fixed by:** `retry.with_retries`, which backs off exponentially with jitter and honours the server's `retryDelay`. On top of it, `retry.with_fallback` moves down a chain of models (3.8 Flash, 3.7 Flash, 3.5 Flash) when one stays unavailable. The storyboard records which model actually answered (`source.model`).
- **Evidence:** `runs.jsonl` stage `smoke` and `script`, status `error`, then `ok` on `gemini-3.5-flash`.

## F2. FLUX.1 schnell rejects a seed

- **What broke:** `HTTP 400: Additional or unevaluated properties '/seed' at '/' not allowed`. The model page's own examples send a seed, but its schema forbids one.
- **Tried:** read the model's input schema from the API (`/ai/models/schema`). Schnell takes only `prompt` and `steps`.
- **Fixed by:** the Cloudflare wrapper sends schnell only what its schema accepts. Schnell images cannot be reproduced by seed, so the content cache is what keeps them stable. It is now only the fallback; FLUX.2 klein (which takes a seed and reference images) is the main image model.

## F3. Kaggle's client imports a package it does not declare

- **What broke:** `No module named 'six'` when importing `kaggle` 2.2.5.
- **Fixed by:** adding `six` to `pyproject.toml`, with a comment saying why.

## F4. The Kaggle GPU quota is 6 hours a week, not about 30

- **What broke:** the brief plans on "about 30 GPU hours a week". Kaggle's quota API reported `totalTimeAllowed: 21600s` (6 h) for this account.
- **Tried:** planned 480p drafts, both T4s in parallel, and a time budget inside the job.
- **Outcome:** this was one reason to move video and music to WaveSpeed (F12).
- **Evidence:** `outputs/smoke/report.json`, `kaggle.gpu_quota`.

## F5. Burmese letters inside an Amharic word

- **What broke:** Gemini wrote `የቅቤ ማိုးዋንና`. The vowel signs U+102D, U+102F and U+1038 are Myanmar script, and the TTS would have mispronounced them.
- **Fixed by:** `storyboard.script_errors`, which rejects any line in a Ge'ez-script language that holds characters outside the Ethiopic blocks. The script stage sends the error back and the model rewrites the line. It caught the problem on the next run.
- **Evidence:** test `test_wrong_script_is_caught`.

## F6. Free-tier daily quotas run out fast

- **What broke:** after a handful of calls, `gemini-3.8-flash`, `gemini-3.7-flash` and `gemini-3.8-flash-tts` all answered 429. The error details say `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 10`, which is 10 requests a day per model, with a retry delay of about 18 hours.
- **Tried:** retrying, which cannot help with a daily quota.
- **Fixed by:**
  - The wrapper tells a daily quota (`QuotaExhausted`) apart from a per-minute one, which it retries.
  - An exhausted model is skipped for the rest of the run instead of being asked again for every line.
  - The chain moves on: 3.8 Flash TTS, then 3.8 Flash Lite TTS. Gemini 2.5 models are retired on 2026-12-01, so they are not a standing fallback.
- **Plan:** speak the real film's lines in one day's quota (10 or fewer per voice model), so every line comes from the same model.

## F7. The voice read its stage direction aloud

The worst bug so far, and the hardest to see, because nothing errored.

- **What broke:** each line was sent with a short English delivery note.
  - **Format 1** (`<note>:\n<line>`): in S10 the voice said "mature, merry, loving, filled with light, teasing humor" instead of the Amharic proverb.
  - **Format 2** (`Say this line in Amharic, <note>, at a natural speaking pace: "<line>"`): the voice said the note first, partly in English and partly translated into Amharic, and then the line.
- **How we found out:**
  - A 4-word line lasted 10.3 s.
  - A pitch check ruled out a wrong sample rate: about 190 Hz, a normal female voice.
  - A loudness envelope showed 10 s of continuous speech.
  - Transcribing the take in 2-second pieces gave "with them", "he too", **"nostalgic at a"**, "but", and then the line itself.
  - The whole-take transcription had matched the script (CER 0.08), so it hid the problem.
- **Fixed by:**
  - **The bare line.** Only the line is sent. It now takes 2.25 s instead of 10.3 s. Delivery comes from the choice of voice; the note stays in the storyboard as documentation.
  - **A length check.** A take longer than its words allow (`narration.too_long`) is re-taken, like a take with high CER.
  - **Retakes.** Up to three per line, keeping the closest.
- **Still open:** sending the note as a system instruction was blocked by the daily quota before it could be tested.
- **Evidence:** `runs.jsonl` narration lines, `outputs/narration/raw/manifest.json` (`heard`, `cer`), tests `test_tts_prompt_is_the_bare_line` and `test_too_long_takes_are_caught`.

## F8. Long pauses inside a line

- **What broke:** S03 had a 2.6 s silence in the middle of a sentence.
- **Fixed by:** post-processing shortens any pause longer than 0.45 s to 0.32 s (`silenceremove`, stop periods). Raw takes are kept, so changing this needs no new TTS calls.

## F9. The first radio cut ran 109 s

- **What broke:** the brief allows 60 to 90 s.
- **Tried:** measured our TTS rate as 1.0 words a second and told the script stage to write fewer words. The next cut ran 131 s anyway, because the "measurement" was F7's spoken notes.
- **Fixed by:** the bare-line fix (F7), then a recalibration from clean takes (about 1.6 to 1.8 words a second, in `script.WORDS_PER_SECOND`). The timeline also stretches pauses evenly when a film comes out under 60 s.

## F10. Captions split mid-phrase

- **What broke:** "...walking nearly three hours down the" ended one caption, and the rest ran on in the next.
- **Fixed by:** captions break at punctuation first, then wrap to two lines of 38 characters. Test `test_captions_split_at_punctuation_and_stay_two_lines`.

## F11. The Windows console could not print Ge'ez script

- **What broke:** `UnicodeEncodeError: 'charmap' codec`.
- **Fixed by:** the CLI switches its output to UTF-8 at start-up, so a stranger on Windows does not hit this.

## F12. Video and music moved from Kaggle to WaveSpeed

- **Why:**
  - Diffusers documents only text-to-video for the Wan 2.2 5B checkpoint, so whether our image-to-video job (keyframe passed as `image`) works was unverified.
  - The official code wants about 24 GB of GPU memory, against a T4's 16 GB.
  - F4 left 6 GPU hours a week.
  - ACE-Step pins its own torch build, which conflicts with Kaggle's.
- **Now:** WaveSpeed's hosted Wan 2.2 I2V 480p Ultra Fast ($0.05 per 5 s, `last_image` for in-betweens) and ACE-Step 1.5 ($0.0003 a second), with one key.
- **Kept:** the Kaggle runner (smoke-tested with a real GPU job) and both Kaggle job scripts, as the `kaggle-wan22-ti2v-5b` and `kaggle-ace-step-1.5` fallback engines. They have not been run end to end.

## F13. WaveSpeed's ACE-Step has no tempo or key fields

- **What broke:** the brief advises keeping tempo and key out of the caption, in their own fields. WaveSpeed's endpoint takes only `tags`, `lyrics`, `duration` and `seed`.
- **Fixed by:** `music.tags_for` appends "76 bpm, E minor, 6/8 time" to the tags. This is a known compromise, kept as it is until the ear says otherwise.

## F14. WaveSpeed's ACE-Step requires lyrics, against its own docs

- **What broke:** `HTTP 400: field "lyrics" is required`. The model page says tags are "the only required field" and that empty lyrics make an instrumental.
- **Fixed by:** instrumentals send ACE-Step's own `[Instrumental]` tag as the lyrics.

## F15. A truncated model file, then a download race

- **What broke:** a model download stopped part way and left an 8 MB `flownet.bin` where 11.4 MB was expected. A re-download then collided with a second process writing the same `.part` file (WinError 32).
- **Fixed by:** downloads go to a per-process `.part` file, are checked against the server's Content-Length, and are renamed only when complete.

## F16. No model could find the mask

- **What broke:**
  - All three Flash models were unavailable at the same moment (3.8 out of quota, 3.7 and 3.5 returning 503). The shots stage crashed at mask lookup.
  - Then a model answered in Gemini's native detection format (`[{"box_2d": ...}]`) instead of the JSON we asked for.
- **Fixed by:**
  - Mask lookup also tries Flash-Lite models.
  - A failed lookup makes that shot fall back (parallax, then pan) instead of stopping the stage.
  - `shots.parse_boxes` reads all three answer shapes.

## F17. One TTS model returns a WAV file, another returns raw PCM

- **What broke:** 3.8 Flash Lite TTS sends `audio/wav` with a RIFF header, while 3.8 Flash TTS sends raw `audio/L16`. Wrapping a WAV in a second header would put a click at the start of every line.
- **Fixed by:** `gemini._decode_audio` reads either.
