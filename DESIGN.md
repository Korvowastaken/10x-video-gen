# Design: audience, intent, and what the audience changed

## Audience and intent

Rewritten on 2026-11-26 for the film as it is now, *From Fear to Laughter*
(Robel's robbery on the way to Samuel's house). The audience below is the one
set in `storyboard.json` (`audience.who`, `where`, `feel`) before the scenes
were drawn; the script stage reads it from there. The earlier version of this
section was for the brief's placeholder story and is in git history.

- **Who watches:** families and close friends who share childhood memories,
  first of all the people who know Robel and Samuel. Many of them speak
  Amharic; some, abroad or younger, follow English more easily.
- **Where:** in a family group chat and in TikTok, Reels or Shorts feeds, on a
  phone, vertical, often with the sound low or off at first. So: English
  captions burned in, top-centre where feed buttons do not cover them, and the
  first shot has to hold attention without sound.
- **What they should feel at the end:** relief and warmth. A scary afternoon
  turns into a story two friends laugh about, and the viewer thinks of the
  friend they would call.

## Choices that follow from the audience

| Choice | Why |
|---|---|
| Vertical first (9:16), 16:9 derived from it | The audience watches in a phone feed or a group chat; the horizontal version is for YouTube and sharing |
| Low-poly 3D look from a TikTok we admired | Familiar to this audience from their feeds; toy-like characters keep a frightening event gentle to watch, and simple faceted faces stay consistent across shots more easily than realistic ones |
| Narration in Amharic, captions in English | The voice carries the feeling for those who understand it; the captions carry the story for friends and family abroad who understand less Amharic |
| One line per shot, cut on the line | The TikTok we studied cuts on every line; it keeps the pace up for a feed |
| The robbery is shown, never the violence | S04 and S05 are held stills of the threat and of Robel's face. The audience knows the people in it; the film is about the fear and what came after, not the attack |
| Light turns from cool to warm | Shadows stay cool blue through the robbery, and the phone call and laughter move into warm lamp and golden light, so the shift from fear to relief reads without sound |
| Bookend: the last shot echoes the first | S11 returns to the S01 street at golden dusk. The film closes like a circle and ends calm, which makes it feel complete in about a minute |
| The laughter is the payoff | It is the moment the audience shares, and the reason to send the film to the friend who was there |

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

## How the studio looks

Set on 2026-11-25. The studio used to look like a grey developer tool, and people found it busy and hard to follow. The new look borrows from the tibeb, the woven coloured border on a habesha kemis or netela. Progress is woven like that border, and each approved step adds its band of colour. The tokens live in `studio/src/index.css`.

**Colours.** Each colour has one job, and nothing uses colour for decoration.

| Token | Light | Dark | Job |
|---|---|---|---|
| `--background` | `#ffffff` | `#121211` | The cloth: page ground |
| `--card` | `#fbfaf7` | `#1a1917` | The rail |
| `--foreground`, `--primary` | `#1d1d1b` | `#f2f0ea` | Ink: text and the one primary button per page |
| `--free` | `#1f7a4d` | `#45a876` | Approved, free, up to date |
| `--gold` | `#e0a800` | `#eab51f` | Where you are: the current step, a scene ready to approve |
| `--warn` | `#b8322a` | `#e5675b` | Needs you: stale, redo, a used-up free limit |
| `--link`, `--ring` | `#1f4e9e` | `#8db0ee` | Links, selection, focus |
| `--paid` | `#9a4a12` | `#eb9a5c` | Paid modes and prices |
| `--thread` | `#cfccc2` | `#4a4740` | Undyed thread: locked steps, empty segments, inputs |

**Type.** Inter for everything, with Noto Sans Ethiopic for Amharic (`lang="am"`). Page titles are 28px semibold, body text 14px, labels 12px. The weights do the ranking, not extra sizes.

**The woven band.** This is the studio's one signature. The `.weave-done`, `.weave-current`, `.weave-stale` and `.weave-locked` classes draw a diamond weave in CSS:
- A 14px band runs down the rail's right edge, one segment per step.
- A full-width strip sits under the Scenes header, one segment per scene, with a legend of counts.

The band shows state and nothing else; it is never decoration.

**Layout rules.**

| Area | Rule |
|---|---|
| Rail | 288px: the 10 Academy logo and "TenX Heritage Short", the six steps as 60px rows (green, gold, red or outline number), then the free limits, the spending bar and Keys |
| Page header | Title, then one line that starts with "Step n of 6". No small label above the title |
| Primary action | One ink button per page: the step's next action |
| Approve bar | Green when approved, red when changed, gold when ready |
| Cards | 1px rules, 5 to 6px corners, no shadows. The only shadow is the job bar's soft lift |
| Modes | Light and dark both follow the system setting |

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

The radio cut came first, played to the same circle of friends and family.
Everyone said it sounded good; there were no negative comments, and no one
pointed at a line or a moment to change. So the radio cut confirmed the words,
voices and pacing, and changed nothing.

**What we change because of it:** nothing. The script and voices went on to
the pictures as they were.

## Test 2: the near-final cut

`outputs/final/heritage_short_9x16.mp4`, shown to at least three people from
the audience (at least one new person).

Shown to friends and family on 2026-11-26. Most of them liked it; not
everyone did.

| Person | How they fit the audience | What they said | Moment (shot) |
|---|---|---|---|
| My parents | Family, Amharic speakers | "This is weird." Did not like it | Not named |
| A friend | A friend, part of the audience | "Oh, this is interesting, I remember that. This is very similar to that." Liked it | Not named |
| Another viewer | From the same family and friends circle | "This looks weird, I don't like it." | Not named |

**What we take from it:** the friend who liked it recognised the story and tied
it to a memory of their own, the reaction the film was made for. The viewer who
said "this looks weird" meant the generated video: in the moving robbery shots
the AI motion did not look good. The fix was to stop moving those shots.

| Feedback | Change | Shots |
|---|---|---|
| "This looks weird, I don't like it": the generated motion in the robbery looked wrong | S04 changed from a paid in-between clip (`flf_inbetween`) to a held still, and S05 from masked motion (`masked_i2v`) to a held still. Both re-approved on 2026-11-26 (15:22 and 15:25 UTC, recorded in `approvals.json` history) | S04, S05 |

The held stills also suit the audience note above: the threat is shown, never
the violence.
