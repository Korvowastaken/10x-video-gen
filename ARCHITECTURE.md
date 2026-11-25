# Architecture

One file is the contract between every stage: `storyboard.json`, validated
against `schema/storyboard.schema.json` and the rules in
`pipeline/storyboard.py` before any stage runs. Each stage reads the
storyboard, writes only its own folders under `outputs/`, and logs every model
call to `runs.jsonl`.

## Steps, approvals and staleness

A person makes the film in six steps (`pipeline/flow.py`). Each step ends in an
approval, and a step opens only when every step before it is approved and
fresh:

| Step | Made by | Approved when |
|---|---|---|
| 1. story | the person, in `story.md` (settings block optional) | the story is long enough and its settings are valid |
| 2. script | `script` stage, `revise.propose_script`, inline edits | the storyboard passes the schema and rules |
| 3. sketch | `sketch.py`: shapes per scene and an animatic, local | every frame matches the storyboard |
| 4. references | `keyframes.references`: one sheet per character and place | every chosen sheet matches its look, photo and seed |
| 5. scenes | `steps.make_scene`: keyframe, voice, motion, preview | each scene on its own, once its picture and lines exist |
| 6. final | `assemble` (final mode) | the film exists |

**Fingerprints.** For each step, and for each scene, `flow.fingerprints()`
hashes what the approval covers, in named parts:

| Fingerprint | Parts |
|---|---|
| story | the text of `story.md` |
| script | the cast, places and scenes' words (order-free), and the story's fingerprint |
| sketch | scene order, framing, figure positions, and the script's fingerprint |
| references | style text, looks, reference prompts, seeds, photos, and the cache key of each chosen sheet |
| scene | the scene's storyboard entry, the keys of its references, keyframe, lines and clip |
| final | every scene's fingerprint, the cut choices (modes, grade, score), the film's report |

Approving writes the fingerprint and its parts to `approvals.json`. A later
status compares parts: the step is **approved** when the hash matches, and
**stale** when it does not, with the changed parts as the reason ("the
script", "the picture"). Nothing is deleted; the cache still holds every file.

The parts follow real dependencies, the same way cache keys do. Editing a line
reopens the script and the sketch (it shows the subtitle) but not the
references. Reordering scenes changes the sketch but not the script. The order
of the steps is enforced separately: a stale step locks every step after it
until it is approved again. `flow.require()` refuses work on a locked step,
from the studio and from the command line alike.

**Versions.** Approving a scene also keeps a copy of its storyboard entry in
`approvals.json` (`history`). Restoring a version writes that entry back and
points the cache manifests at the files it made, so an old version comes back
with no model calls.

**Money.** `storyboard.rule_errors()` rejects a scene whose motion mode is not
in `video.allowed_modes`, and any set of paid modes that costs more than
`video.budget_usd` for the whole film. Paid API actions need `confirm_usd` at
least the price; the command line needs `--buy` and buys one clip at most.

## The stages under the steps

```
story.md ──script──► storyboard.json ◄── edited in the studio or by hand from here on
                          │
   ┌──────────────┬───────┴────────┬────────────────┐
   ▼              ▼                ▼                ▼
 keyframes     narration         music            shots
 FLUX.2 klein  Azure Speech      ACE-Step 1.5     per shot, by motion.mode:
 (Cloudflare)  + listen-back     (WaveSpeed)      paid clip (WaveSpeed Wan 2.2 I2V)
   │              │                │              + local: masks, depth (laptop)
   └──────────────┴───────┬────────┴────────────────┘
                          ▼
                assemble (laptop, deterministic)
   RIFE retiming · parallax · loops · Ken Burns · captions · ducking · loudness
        radio cut · rough cut · final 9:16 + 16:9 · end card · .srt
```

## Stages and their contracts

| Stage | Reads | Writes | Runs on |
|---|---|---|---|
| `script` | `story.md` | `storyboard.json` (the previous one backed up to `outputs/script/`) | storyboard in English: Claude Haiku 5.5; spoken lines in the film's language: Claude Sonnet 5.5; Gemini 3.5 Flash as the fallback for both |
| `keyframes` | characters, locations, shots | `outputs/refs/` (character sheets, places), `outputs/keyframes/` (each shot's still, plus `<shot>_end` for in-betweens), contact sheets | FLUX.2 klein 4B with reference images on Cloudflare Workers AI; FLUX.1 schnell as fallback |
| `narration` | lines, voices | `outputs/narration/raw/` (takes), `outputs/narration/` (processed lines), `timing.json` | Azure Speech neural voices (then Gemini 3.8 Flash TTS and 3.8 Flash Lite TTS); Azure speech-to-text listens back (then gemini-3.5-transcribe) |
| `music` | `music` block | `outputs/music/candidate_<n>.flac` | ACE-Step 1.5 on WaveSpeed (fallback engine: Kaggle) |
| `shots` | keyframes, `motion` per shot, `video` limits | `outputs/shots/raw/` (bought clips), `outputs/shots/` (masked composites), `outputs/shots/masks/`, `outputs/depth/` | Wan 2.2 I2V 480p Ultra Fast on WaveSpeed (fallback engine: Wan 2.2 TI2V-5B on Kaggle); masks by Gemini; depth by Depth Anything V2 Small on the laptop |
| `assemble` | everything above | `outputs/cuts/` (radio, rough), `outputs/final/` (9:16, 16:9, `.srt`, report) | FFmpeg, OpenCV, RIFE on the laptop |

`make film` runs them in this order: script, keyframes, narration, music,
shots, assemble. Each stage also runs alone (`make shots`) or for some shots
(`make shots ONLY=S03`).

## Motion: one mode per shot, paid only where it shows

Each shot's `motion.mode` decides how it moves; `pipeline/engines.py` holds
the modes and the engines behind them. The defaults follow the "balanced" plan
in `research/motion-on-a-budget.md`.

| Mode | What the viewer sees | How it is made | Cost |
|---|---|---|---|
| `full_i2v` | the whole frame moves (walking, a big gesture) | one image-to-video clip from the keyframe | $0.05 (5 s) or $0.08 (8 s) |
| `flf_inbetween` | a move from one pose to another | the same model with `last_image` set to the shot's end keyframe, drawn with the start keyframe as a reference | $0.05 |
| `masked_i2v` | only part of the frame moves (face, hands) | one clip composited onto the still through a feathered mask, then aligned and colour-matched | $0.05 |
| `cinemagraph` | one looping detail (steam, pouring) | as masked_i2v, ping-ponged to any length | $0.05 |
| `parallax` | a small 3D camera move over a still | a depth map (Depth Anything V2 Small, ONNX) plus `cv2.remap` | free |
| `still_kenburns` | a slow pan or zoom | FFmpeg `zoompan` | free |
| `still` | the still, held | | free |

**Masks** come from `motion.mask.target`, plain words such as "the steam
above the cups". Gemini draws boxes around it on the keyframe; they are
padded, turned into feathered ellipses and cached by keyframe and target.
`motion.mask.regions` can set the shapes by hand instead.

**Retiming.** WaveSpeed returns 30 fps (EXPERIMENTS E8). Assembly resamples
each clip to 24 fps and, when a shot is longer than its clip, slows it down by
at most 1.25x for characters or 1.6x for ambient motion (`motion.subject`).
RIFE v4.25 synthesises the frames in between; the rest of the shot holds the
last frame. Ping-pong loops fill a shot of any length.

**Grade.** Assembly moves each scene's colours part of the way (`edit.grade_strength`,
0.6) toward the film's look: the median Lab mean and spread of all keyframes,
or a fixed `edit.grade.target`. `pipeline/grade.py` bakes this into a 33-point
3D LUT per scene that FFmpeg applies to every frame; the LUT's hash is in the
segment's cache key (EXPERIMENTS E14).

**Cut choices.** `edit.use` maps a scene to the mode the final cut should use
instead of its own, for example parallax instead of a bought clip.

**Spending limits.** `video.max_paid_clips` (7) and `video.budget_usd` ($0.60)
cap what one run may buy; `make shots` reports every clip it bought or
skipped. A WaveSpeed submit is never retried after an unclear failure (a retry
could create a second billed task); only a 429, which creates nothing, is
retried. Polling and downloads retry freely.

**Fallback chain.** When a paid shot has no clip (over the limit, no credit,
3 failed attempts, or no mask found), assembly walks `engines.FALLBACK`: first
parallax, then a slow pan. The film is always complete, and the final report
lists which shots fell back. The rough cut uses this chain deliberately: it
skips paid modes, showing what the film looks like for free.

## What the storyboard holds, and why

Everything a person might change or explain lives in the storyboard, not in
code: every prompt, seed, voice, line, subtitle, music brief, ducking setting,
motion mode, mask target, end-frame prompt, spending limit and model or engine
ID. Code holds only how those are combined:

- **Style block.** One fixed look description (`style.block`) is prepended to
  every image prompt.
- **Looks.** Each character's `look` is repeated word for word in every shot
  that shows them. `storyboard.image_prompt()` is the only place prompts are
  composed, so a thing is never described two ways.
- **Motion prompts.** These describe only motion and camera. Masked modes get
  "static locked-off camera" added automatically, so the clip lines up with
  the still.

The script stage drafts the creative half and code fills the technical half
(seeds, models, limits). It works in two steps. First a cheap model with no
strict daily limit (`models.script`, Claude Haiku 5.5) writes the whole
storyboard in English, every spoken line included; the English becomes the
subtitle. Then only the spoken lines go to the model best at the film's
language (`models.lines`, Claude Sonnet 5.5), with the story and the cast, to
be written the way a speaker would say them. Code checks the script and that
each shot's words fit its length, and sends problems back (3 attempts). Most
of the tokens are in the first step, so the strong model sees only a few
hundred words. A film in English skips the second step. `source.model` and
`source.lines_model` record who wrote what.

It regenerates the storyboard only when `story.md` changes
(`source.story_sha256`), so hand edits survive.

### Providers and fallback chains

Writing and voices name a chain of models in `storyboard.json`, and
`pipeline/providers/route.py` tries them in order across providers. The id
says the provider: `claude-...` is Anthropic, `azure-neural` and `azure-stt`
are Azure AI Speech, `groq/...`, `cerebras/...` and `openrouter/...` are
OpenAI-style hosts with free tiers, and anything else is Gemini. A provider
with no saved key is skipped without a call, so the chain works with whatever
keys a person has. Gemini's free tier (about 10 requests a day per model) is
now the fallback rather than the first choice.

Azure has one female and one male neural voice for Amharic. The storyboard's
voice (a Gemini voice name) picks Azure's voice by pitch and shifts it a few
percent by its character, so two speakers still sound apart. A line spoken by
Azure has its own cache key (`azure_voice`), and lines already spoken by
Gemini keep theirs, so switching an existing film to Azure re-speaks its lines
once, on purpose.

### Validation

The JSON Schema checks shape and types, including the per-mode requirements:
an in-between needs `end_keyframe`, a masked shot needs a `mask`.
`storyboard.rule_errors()` adds the checks a schema cannot make:

- **References resolve.** Every speaker, on-screen character and location
  exists, a voice-only narrator never appears on screen, and shots are in
  order.
- **Engines can do the job.** Every engine exists and can do what its shot
  asks: an in-between needs `last_image`, and the clip length must be one the
  engine sells.
- **Text is in the right script.** Lines in a Ge'ez-script language contain
  only Ge'ez characters (FAILURES F5).
- **Consent.** A real person needs a consent row in `ETHICS.md`. Without it,
  nothing runs.

## Caching: a re-run regenerates only what changed

Every output is `outputs/<stage>/<item>__<key>.<ext>`, where the key is a hash
of everything that produced it. `manifest.json` in each folder maps items to
files and to the spec behind each key.

| Output | Its key covers |
|---|---|
| reference sheet | style block, look, reference prompt, seed, primary image model, size |
| keyframe | composed prompt, seed, model, size, **hashes of its reference images** |
| end keyframe | end prompt, seed, model, **hash of the start keyframe** and the other references |
| TTS take | line text, voice, primary TTS model, prompt format |
| narration line | the take's key + post-processing version |
| music candidate | engine, tags (caption + tempo, key, metre), length, seed |
| bought clip | engine, **keyframe hash**, end-keyframe hash, motion prompt, negative prompt, seed, clip length |
| mask | keyframe hash + target words |
| composite | clip hash, still hash, mask regions, feather, alignment, loop mode |
| depth map | keyframe hash + depth model |
| edit segment | source kind and file hashes, duration, size, fps, pan or parallax settings, stretch cap, RIFE model |

Keys chain, so a change flows only down its own path:

- **A keyframe prompt changes:** one new keyframe, then one new clip, depth
  map and segment. Nothing else is touched.
- **A line changes:** one TTS call, one re-processed line, and re-rendered
  segments only where shot timings moved.
- **A post-processing change** re-processes from the stored raw takes, with
  no model calls.

Only the primary model is in a key, so editing a fallback list does not
regenerate anything. The model that actually answered is recorded per item.
Cache hits make no calls and write nothing to `runs.jsonl`: after a one-line
edit, the log gains exactly that one line's calls.

`outputs/` is git-ignored: the cache lives on the machine that made it, and a
fresh clone regenerates from `story.md` and `storyboard.json` (keys needed).
What a reader of the repository can check is committed as text: every model
call in `runs.jsonl`, and the measurements copied into `EXPERIMENTS.md`,
`FAILURES.md` and `COSTS.md`.

## Failure handling

| What fails | What the pipeline does |
|---|---|
| 429 per-minute limit, 5xx, timeout, dropped connection | `retry.with_retries`: exponential backoff with jitter, honouring `retryDelay`; every attempt logged |
| A model stays overloaded (Gemini 503, Claude 529), refuses, or has no key saved | `route.py` moves down the storyboard's model chain, across providers |
| A quota is used up (Gemini free tier, Azure's month, Anthropic credit, Cloudflare neurons, WaveSpeed credit) | `QuotaExhausted`: the model is skipped for the rest of the run, the chain moves on or the shot falls back |
| WaveSpeed submit fails in an unclear way | not retried (no double billing); the shot counts one failed attempt, at most 3 |
| The voice reads its stage direction, mispronounces, or adds speech | only the bare line is sent; listen-back CER and a length check trigger a retake (up to 3) and the closest take wins |
| FLUX.2 fails or its allowance is gone | FLUX.1 schnell, without references |
| No clip, no credit, no mask | the shot falls back to parallax, then a slow pan; logged in the final report |
| RIFE cannot start (no Vulkan, no CPU support) | frames repeat instead; the edit goes on |
| A model download is interrupted | per-process `.part` file, size checked against Content-Length before use |
| Model output in the wrong script, invalid JSON, schema errors | the script stage feeds the errors back and asks for a corrected draft (3 attempts) |
| Real person without consent | validation error before any generation |

## Fallback providers: Kaggle

`pipeline/providers/kaggle_runner.py` treats Kaggle as a batch GPU. It uploads
`job.json` plus inputs as a private dataset version, pushes a script kernel
with GPU and internet on, polls until it finishes, downloads
`/kaggle/working`, and rejects results from another job through a `job_id`
round trip. The runner is smoke-tested with a real GPU job. Two job scripts
use it:

- `pipeline/kaggle/wan_i2v.py`: Wan 2.2 TI2V-5B, one transformer on each T4,
  prompts encoded once.
- `pipeline/kaggle/acestep_music.py`: ACE-Step in its own uv environment.

They are kept as the `kaggle-*` engines and have not been run end to end (see
FAILURES F12 for why the main path moved to WaveSpeed).

## Logging

One line per model call, successful or not: `ts, run_id, stage, item,
provider, model, params, seed, attempt, status, latency_s, gpu_s, cost,
cache_key, output, error, note`. For WaveSpeed, `gpu_s` is the provider's
inference time and `cost.usd_list` the list price. Prompts are logged as a
length and a hash; the full text is in `storyboard.json`. `make costs`
summarises the log per stage for `COSTS.md`.

## The studio

`uv run python -m pipeline studio` builds the React app in `studio/` and serves
it with the API in `pipeline/studio.py` and `pipeline/flow_api.py` (FastAPI,
127.0.0.1:8765). `GET /api/flow` returns the steps, each scene's state, prices
and the budget; the step actions run `pipeline/steps.py`, the same functions as
the command line. The studio never holds its own
state: every edit writes `story.md` or `storyboard.json` through the same schema
and rule checks as `make validate`, and every button runs the same stage
function the CLI runs, one job at a time, with its log streamed back. So a scene
redone from the browser hits the same cache as `make shots ONLY=S03`.

Scene feedback goes through `pipeline/revise.py`: the lines writer (`models.lines`, then `models.script`) proposes a revised shot
from the note, the studio shows the diff, and nothing changes until you accept
it. The shot keeps its id and seeds, so only the parts the note touched are
regenerated. Reference photos are saved in `references/` (git-ignored, since
they can show real people) and fed to FLUX next to the character sheet.

## Layout

```
story.md                 the input: the family story, with optional settings
storyboard.json          the contract (generated, then edited in the studio or by hand)
approvals.json           what was approved, and each scene's earlier versions
GLOSSARY.md              the words for steps, scenes, sketches and so on
schema/                  JSON Schema for the storyboard
research/                the motion-on-a-budget study behind the motion modes
pipeline/                one module per stage, plus engines.py, motion.py and the core;
                         flow.py (steps, approvals), steps.py (step actions), sketch.py, grade.py
pipeline/providers/      route.py (chains across providers), anthropic_api.py, azure_speech.py,
                         openai_compat.py, gemini.py, cloudflare.py, wavespeed.py, kaggle_runner.py
pipeline/kaggle/         the scripts the Kaggle fallback engines run
tests/                   contract, caching, motion and edit tests (`make test`)
outputs/                 everything generated, kept so a run can be inspected
runs.jsonl               one line per model call
.models/                 RIFE and Depth Anything weights, fetched on first use (git-ignored)
```
