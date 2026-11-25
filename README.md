# 10x video gen: a heritage short, made in code

A small studio in code. You write a family story in plain words in
`story.md`; the pipeline turns it into a 60-90 second vertical short film with
narration in your language, English subtitles, an original score ducked under
the voice, and an end card saying it was made with AI. Every picture, voice
and note comes from a model, and every model call is logged in `runs.jsonl`.

The look follows a TikTok style we liked: toy-like low-poly 3D characters,
warm light against deep blue, shallow focus, captions top-centre. The
characters are our own.

## One command

```sh
make film        # or, without make:  uv run python -m pipeline film
```

That runs `script → keyframes → narration → music → shots → assemble` and
writes:

- `outputs/final/heritage_short_9x16.mp4`: vertical, 1080x1920
- `outputs/final/heritage_short_16x9.mp4`: horizontal, 1920x1080
- `outputs/final/heritage_short.en.srt`: the English subtitles as a file
- `outputs/final/heritage_short.report.json`: length, loudness, and which motion each shot ended up using

Everything the pipeline makes goes to `outputs/`, which is git-ignored: the
films are shared as links, and `make film` rebuilds everything else from
`story.md` and `storyboard.json`. On a fresh clone that means the keys below
and about $0.45 of WaveSpeed credit. On your own machine every stage is
cached, so a re-run regenerates only what changed.

## Setup

1. Install [uv](https://docs.astral.sh/uv/). `uv sync` installs Python 3.12
   and every dependency, including an FFmpeg binary (`imageio-ffmpeg`), OpenCV,
   ONNX Runtime and RIFE. A system FFmpeg is used first if one is on `PATH` or
   set in `FFMPEG_BIN`. The RIFE and Depth Anything weights download into
   `.models/` on first use.
2. `cp .env.example .env` and fill in the keys you need:

| Key | Used for | Cost | Where |
|---|---|---|---|
| `GEMINI_API_KEY` | script, narration, listen-back, finding masks | free tier | aistudio.google.com/app/apikey |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | keyframes (FLUX.2 klein) | free 10,000 neurons a day | dash.cloudflare.com, then Profile, API Tokens, "Workers AI" template |
| `WAVESPEED_API_KEY` | moving shots (Wan 2.2 I2V) and score (ACE-Step 1.5) | pay per use; new accounts may get $1 | wavespeed.ai |
| `KAGGLE_API_TOKEN` | fallback engines only | free, 6 GPU hours a week on our account | kaggle.com/settings, then API |

3. `make smoke` calls each provider once, lists the models available today,
   and logs latency. Add `GPU=1` to also run a one-minute Kaggle GPU job.

`.env` is git-ignored; no key ever goes into the repository.

## Making your own film

1. Write your story in `story.md`: keep the settings block (language, look,
   length, audience, real people), then a few paragraphs in any language.
2. If a real person appears or is voiced, add their consent row to
   `ETHICS.md` first. The pipeline refuses to generate them without it.
3. `make radio`: drafts the storyboard, speaks the lines, and writes
   `outputs/cuts/radio_cut.mp4` (voice over placeholder music on black, with
   subtitles and shot labels). Show it to three people from your audience and
   write what they said in `DESIGN.md`.
4. Edit `storyboard.json` (lines, prompts, voices, motion) based on what they
   said, then `make rough`: every shot moves for free (parallax and pans), so
   you can judge pacing before buying any clips.
5. `make music`, listen to `outputs/music/`, then set `music.chosen` and
   `music.chosen_reason`.
6. `make film` buys the paid clips (within your limits) and exports the film.

### How each shot moves

Each shot's `motion.mode` decides; paid modes buy one 480p clip from
WaveSpeed (Wan 2.2 I2V Ultra Fast), free modes run on your machine.

| Mode | For | Cost |
|---|---|---|
| `full_i2v` | whole-body action, walking | $0.05 (5 s), $0.08 (8 s) |
| `flf_inbetween` | a move from this keyframe to an end keyframe (`last_image`) | $0.05 |
| `masked_i2v` | only part of the frame moves (`mask.target` in words) | $0.05 |
| `cinemagraph` | one looping detail: steam, pouring, leaves | $0.05 |
| `parallax` | establishing shots, landscapes (depth map + camera move) | free |
| `still_kenburns`, `still` | inserts and details | free |

`video.max_paid_clips` and `video.budget_usd` in the storyboard cap what one
run may spend. A shot that gets no clip falls back to parallax, then to a slow
pan, so the film is always complete. `research/motion-on-a-budget.md`
explains the plan: 7 paid clips, about $0.38 per film at list price.

### Regenerate one shot

Change one `keyframe.prompt` (or one line's `text`) in `storyboard.json`, then:

```sh
make film          # or step by step: make keyframes ONLY=S03; make shots ONLY=S03; make assemble
make status        # what is cached
```

Only that shot's keyframe, clip and edit segment are regenerated, or only that
one line for a narration edit. The new lines at the end of `runs.jsonl` show
the single model call.

## Commands

| Command | What it does |
|---|---|
| `make film` | every stage, then the final 9:16 and 16:9 films |
| `make radio` / `make rough` | the two test cuts: voice on black, and free motion over the stills |
| `make script` | draft `storyboard.json` from `story.md` (only when the story changed; `FORCE=1` to redraft) |
| `make keyframes`, `narration`, `music`, `shots`, `assemble` | one stage; `ONLY=S03,S05` limits to shots, `FORCE=1` ignores the cache |
| `uv run python -m pipeline shots --max-paid 1` | buy at most one clip this run |
| `make validate` | check the storyboard against the schema, the engines, the consent and script rules |
| `make status` | which shots have keyframes, lines and clips cached |
| `make costs` | per-stage calls, latency, GPU time and list-price cost from `runs.jsonl` |
| `make test` | the contract, caching, motion and edit tests |

## What it costs

| Item | Cost |
|---|---|
| Script, narration, masks | free tier (a few calls a day on the newest Gemini models) |
| Keyframes | free (10,000 Cloudflare neurons a day; about 240 per keyframe with references) |
| Clips | about $0.38 per film at list price with the balanced plan |
| Score | 3 candidates of about 80 s, about $0.07 |

`COSTS.md` has measured latency per stage and list-price equivalents.

## Documents

- `ARCHITECTURE.md`: stages, the storyboard contract, motion modes, caching, failure handling
- `DESIGN.md`: audience, intent, the two audience tests and what changed
- `EXPERIMENTS.md`: hypothesis, change and result for each experiment
- `FAILURES.md`: what broke, what we tried, what fixed it
- `COSTS.md`: measured latency, GPU time, list-price equivalents
- `ETHICS.md`: consent records, licences, labelling plan
- `research/motion-on-a-budget.md`: how we cut paid video by more than half

> **Status.** `story.md` holds the brief's example story (a girl walking to
> the market in Dessie), used to build and test the pipeline end to end; the
> family story replaces it for the published film. Its narration was spoken
> before the bare-line fix (FAILURES F7) and is re-spoken with the real story.
