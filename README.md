# 10x video gen: a heritage short, made in code

You write a family story in plain words. The studio turns it into a 60-90
second vertical film with narration in your language, English subtitles, an
original score under the voice, and an end card that says it was made with AI.
You go through four steps, and each one waits for your approval before the next
one opens. Every model call is logged in `runs.jsonl`.

## Setup

1. Install these once, then **open a new terminal** so it finds them (in VS
   Code, close every VS Code window and open it again):

   | Tool | Windows | macOS |
   |---|---|---|
   | [Git](https://git-scm.com) | `winget install Git.Git` | `brew install git` |
   | [uv](https://docs.astral.sh/uv/getting-started/installation/) | `winget install astral-sh.uv` | `brew install uv` |
   | [Node.js LTS](https://nodejs.org), which includes npm | `winget install OpenJS.NodeJS.LTS` | `brew install node` |

   On Linux, follow the links. You do not need to install Python or FFmpeg:
   `uv sync` brings both.

2. Get the project and its dependencies:

   ```sh
   git clone https://github.com/Korvowastaken/10x-video-gen heritage-studio
   cd heritage-studio
   uv sync
   ```

3. Copy `.env.example` to `.env` (`copy` in Command Prompt, `cp` in PowerShell,
   macOS and Linux) and fill in your own keys, listed under [Keys](#keys).

4. Start the studio and open <http://localhost:8765>:

   ```sh
   uv run python -m pipeline studio
   ```

   The first start builds the web app, which takes about a minute. Starting
   it makes no model calls. Ctrl+C stops it.

| If you see | Do this |
|---|---|
| `'uv' is not recognized` or `command not found` | Open a new terminal; in VS Code, restart VS Code fully |
| `Errno 10048` or `address already in use` | The studio is already running: use that page, or press Ctrl+C in its terminal |
| `needs Node.js` | Install Node.js (step 1), then open a new terminal |

## The four steps

```
 1 Story ─► 2 Script ─► 3 References ─► 4 Film
 plain      lines,      character and   each scene's picture, voice and motion,
 words      subtitles   place sheets    then the cut: 9:16 + 16:9, captions,
                                        score, end card
     each step: work on it ─► approve ─► the next step opens
     change something upstream ─► the steps after it turn stale (nothing is deleted)
```

| Step | What you do | Cost | Command line |
|---|---|---|---|
| 1. Story | Type or paste the story, in any language. Spoken language, look, length and audience have defaults; change them under Settings. | free | write `story.md`, then `approve story` |
| 2. Script | Draft it: scenes, Amharic lines, English subtitles, who speaks. Edit lines in place, or ask for a revision in plain words. Accept it. | free (Gemini free tier) | `script --force`, `revise script "..." --accept`, `approve script` |
| 3. References | Upload photos of the people and places you have. The pipeline draws a reference sheet for each character and place; pick one or draw another. Real people need a consent row in `ETHICS.md` first. | free (Cloudflare free tier) | `references`, `approve references` |
| 4. Film | Make scenes one at a time or several at once. For each, everything sits in one panel: edit the still, the lines and their voice tuning, and the motion, leave a note for the writer, tick what to redo (still, voice or clip) and redo it, then approve. Set which modes are allowed and the film's budget. Then choose which mode each scene uses in the cut, pick a score and make the film. | free, except paid motion modes ($0.05 a clip); the score is about $0.07 | `scene S03`, `scene S03 --buy`, `revise S03 "..."`, `approve scenes S03`, `cut`, `approve final` |

Every command is `uv run python -m pipeline <command>`. `flow` prints where the
film is: each step approved, stale or locked, what is missing, and the budget.

```
$ uv run python -m pipeline flow
  1. Story       ok
  2. Script      ok
  3. References  STALE  ; changed: the references
  4. Scenes      locked
  ...
  budget $0.60: chosen modes $0.38, still to buy $0.33, spent so far $0.05
  next: References
```

Paid actions always show their price. The studio asks before spending, and the
API refuses a paid action unless the price was confirmed. Nothing is bought
from the command line without `--buy`, and then only one clip.

### Motion modes

| Mode | What moves | Cost |
|---|---|---|
| Still | nothing, the picture is held | free |
| Ken Burns | a slow pan or zoom over the picture | free |
| Parallax | a small 3D camera move from a depth map | free |
| Full motion (`full_i2v`) | the whole frame: walking, a big gesture | $0.05 (5 s), $0.08 (8 s) |
| In-between (`flf_inbetween`) | a move from this picture to an end picture | $0.05 |
| Masked motion (`masked_i2v`) | only part of the frame, the rest stays still | $0.05 |
| Cinemagraph | one looping detail: steam, pouring, leaves | $0.05, then loops for free |

The budget (`video.budget_usd`, $0.60 by default) caps what the whole film may
spend on clips, and `video.allowed_modes` limits what a scene may choose. A
paid scene with no clip yet plays as parallax in previews and in the cut.
`research/motion-on-a-budget.md` explains the plan: 7 paid clips, about $0.38
a film.

## Keeping it consistent

Faces stay the same from scene to scene because each keyframe is drawn with
the approved reference sheets as input images, with seeds fixed in
`storyboard.json` and the same style text at the start of every picture prompt.
The final cut also moves every scene's colours part of the way toward the
film's average with a per-scene 3D LUT; neighbouring scenes came out 30% closer
in colour (EXPERIMENTS E14). Lines are normalised to -18 LUFS and the film to
-14 LUFS, and captions use one style, top-centre on vertical. Every file is
cached under a hash of everything that made it, so a run with no changes makes
no model calls and reuses every file.

## Where things go

| Path | What |
|---|---|
| `story.md` | your story, with an optional settings block at the top |
| `storyboard.json` | the script, scenes, prompts, seeds, modes and limits: the contract between steps |
| `approvals.json` | what you approved, and when, with every scene's earlier versions |
| `references/` | uploaded photos (git-ignored: they can show real family members; a fresh clone draws the characters from their descriptions instead) |
| `outputs/refs/`, `outputs/keyframes/` | reference sheets and scene pictures |
| `outputs/narration/`, `outputs/music/`, `outputs/shots/` | voices, score candidates, bought clips |
| `outputs/preview/` | one preview per scene |
| `outputs/final/` | `heritage_short_9x16.mp4`, `_16x9.mp4`, `.en.srt`, and a report with length, loudness and the mode each scene used |
| `runs.jsonl` | one line per model call: model, latency, cost |

`outputs/` is git-ignored. Everything in it can be rebuilt from `story.md` and
`storyboard.json`, and on your own machine the cache only redoes what changed.

## Keys

| Key | Used for | Cost | Where |
|---|---|---|---|
| `GEMINI_API_KEY` | script, revisions, narration, listen-back, masks; pictures if a Nano Banana model is picked | free tier (pictures are paid, about $0.03-0.13 each) | aistudio.google.com/app/apikey |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | reference sheets and keyframes (FLUX.2 klein) | free 10,000 neurons a day | dash.cloudflare.com, Profile, API Tokens, "Workers AI" template |
| `WAVESPEED_API_KEY` | paid clips (Wan 2.2 I2V) and the score (ACE-Step 1.5) | pay per use | wavespeed.ai |
| `KAGGLE_API_TOKEN` | fallback engines, and pictures if FLUX.2 klein on Kaggle is picked | free GPU hours | kaggle.com/settings, API |

`uv run python -m pipeline smoke` calls each provider once. When a free quota
runs out, the pipeline asks before it uses the next provider in the list
(on the studio's job bar, or y/n in a terminal). Shots then fall back to a
free motion mode, and the score to a placeholder.

## Without the gates

The stages under the steps also run on their own, for scripting and
experiments. They ignore approvals.

| Command | What it does |
|---|---|
| `film` | every stage in order, then the final 9:16 and 16:9 films |
| `radio`, `rough` | test cuts: voice on black, and free motion over the pictures |
| `script`, `keyframes`, `narration`, `music`, `shots`, `assemble` | one stage; `--only S03,S05` limits it to scenes, `--force` ignores the cache |
| `validate`, `status`, `costs`, `prune` | check the storyboard, list what is cached, sum `runs.jsonl`, delete unused files |
| `site` | the design doc as one page: `outputs/site/index.html` |

`make` wraps the same commands (`make film`, `make test`) if you have it.
`uv run pytest -q` runs the tests.

## Documents

- `GLOSSARY.md`: the words the studio, the code and these docs use
- `ARCHITECTURE.md`: steps, approvals and staleness, stages, caching, failure handling
- `DESIGN.md`: audience, intent, the audience tests and what changed
- `EXPERIMENTS.md`, `FAILURES.md`, `COSTS.md`: what we measured, what broke, what it cost
- `ETHICS.md`: consent records, licences, labelling
- `research/motion-on-a-budget.md`: how we cut paid video by more than half

## Thanks

- **Samuel Birhanu**, from the cohort Slack, shared `model-options.md`: research on which free and cheap hosted models fit each stage. It led us to move video and music from Kaggle notebooks to WaveSpeed's APIs (FAILURES F12), which made the pipeline a reusable piece of software instead of a notebook workflow.

> **Status.** `story.md` holds the brief's example story (a girl walking to
> the market in Dessie), used to build and test the pipeline end to end; the
> family story replaces it for the published film.
