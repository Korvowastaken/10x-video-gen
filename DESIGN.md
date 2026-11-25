# Design: audience, intent, and what the audience changed

## Audience and intent

Set on 2026-11-25 in the settings block of `story.md` (`audience`, `feel`)
before the first storyboard was drafted; the script stage reads them from
there. This section spells them out.

- **Who watches:** young Ethiopians at home and in the diaspora, 18 to 35, who
  grew up hearing their grandparents' stories but rarely ask for them now.
- **Where:** on a phone, vertical, in a TikTok, Reels or Shorts feed, often with
  the sound low or off at first. So: English captions burned in, top-centre where
  feed buttons do not cover them, and the first shot has to hold attention
  without sound.
- **What they should feel or understand at the end:** warmth and pride for the
  long walks our grandparents made, and the urge to call them. The proverb is
  the thing to remember.

> These answers are for the placeholder story (the brief's example). When the
> family story replaces it, rewrite this section first, dated, before
> regenerating.

## Choices that follow from the audience

| Choice | Why |
|---|---|
| Vertical first (9:16), 16:9 derived from it | The audience watches in a phone feed; the horizontal version is for YouTube and sharing |
| Low-poly 3D look from a TikTok we admired | Familiar to this audience from their feeds; stylised characters avoid the uncanny look of AI "photos" of real elders, and simple faceted shapes stay consistent across shots more easily than realistic faces |
| Narration in Amharic, captions in English | The voice carries the feeling for those who understand it; the captions carry the story for cousins abroad who understand less Amharic |
| One line per shot, cut on the line | The TikTok we studied cuts on every line; it keeps the pace up for a feed |
| Present day framing a remembered past | Present scenes lit by a lamp at night, the past in dawn and golden light, so the two times read at a glance |
| Bookend: the last shot echoes the first | The film closes like a circle, which makes it feel complete in 75 seconds |
| A proverb as the payoff | It is short, repeatable and shareable; it is what the audience can say to their own families |

Every shot's reason is in `storyboard.json` (`shots[].reason`).

## Who makes the film, and how the studio follows from that

The person making the film is usually the grandchild who heard the story. They
know what the story should feel like, but not what a seed or a motion mode is. Updated 2026-11-25, when the studio became a
six-step flow (ARCHITECTURE.md, "Steps, approvals and staleness").

| Choice | Why |
|---|---|
| The story is plain text in any language; settings have defaults | Nobody should have to learn YAML to start. Most people never open the settings |
| Six steps, each approved before the next opens | Each decision is made once, in order: the words, then the composition, then the faces, then the motion. Changing the words after the pictures exist is the expensive mistake this prevents |
| A shape sketch and animatic before any picture | Order, framing and pacing can be judged for free in a minute. Generated pictures make people judge the faces instead |
| Upstream edits mark later work stale and keep it | The later work needs another look, but it is kept. People undo edits, and the cache brings the old files back for free |
| Feedback in plain words, shown as a diff, then accepted | The person describes the change ("she should smile here"). Gemini rewrites the scene, and nothing changes without their yes |
| Every action shows its price; paid ones ask first | Free actions should feel safe to click. The only money spent is on clips and the score, and it is always a deliberate choice |
| Allowed modes and a film budget, set once | The person sets the spending once for the whole film |

## Test 1: the radio cut

`outputs/cuts/radio_cut.mp4` is the narration over placeholder music on a black
screen, with English captions and shot labels (S01, S02 ...) so people can
point at a moment. Shown to at least three people from the audience, in person
or on Slack.

Questions asked after one viewing, without explaining first:
1. In one sentence, what was the story about?
2. Where did you lose interest, if anywhere? (Name the shot label.)
3. What did you feel at the end?
4. Which line do you remember?
5. For Amharic speakers: which words sounded wrong or unnatural?

| Person (first name or role) | How they fit the audience | What they said | Moment (shot) |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

**What we change because of it** (each change made in `storyboard.json`; the git history shows the diff):

| Feedback | Change | Shots |
|---|---|---|
| | | |

## Test 2: the near-final cut

`outputs/final/heritage_short_9x16.mp4`, shown to at least three people from
the audience (at least one new person).

| Person | How they fit the audience | What they said | Moment (shot) |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

| Feedback | Change | Shots |
|---|---|---|
| | | |
