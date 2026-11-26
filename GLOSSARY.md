# Glossary

The words this repo uses for turning a family story into a short film. The
studio, the command line, the code and the docs all use them the same way.

## The workflow

**Step**:
One of the five stages a person goes through, in order: story, script, references, scenes, final cut (the studio shows the last two as one Film page). Each ends with an approval.
_Avoid_: phase, gate (as a noun for the step itself)

**Approval**:
A person's "yes, this is right" on a step, or on one scene, as it is at that moment.
_Avoid_: sign-off, accept (except for a proposed revision)

**Stale**:
An approved step or scene whose content, or something it was made from, has changed since it was approved. Its work is kept, not deleted.
_Avoid_: outdated, invalid, dirty

**Locked**:
A step that cannot be worked on yet because a step before it is not approved, or is stale.
_Avoid_: blocked, disabled

**Version**:
One approved state of a scene. Earlier versions can be put back, and their files come back from the cache for free.
_Avoid_: revision (that is a proposal), take (that is a voice recording)

## What gets made

**Story**:
What the person wrote, in plain words and in any language, with optional settings (spoken language, look, length, audience).

**Script**:
The film in words: the cast, the places, and each scene's beat, spoken lines, English subtitles and length.
_Avoid_: screenplay, draft

**Revision**:
A change to the script or to one scene that Gemini proposes from a note in plain words. Nothing changes until it is accepted.
_Avoid_: feedback (that is the note), edit (that is done by hand)

**Sketch**:
The layout guide: one plain frame per scene, outline figures with simple arms and legs on white, showing where each person stands, how big they appear and which way they face. It is sent to FLUX.2 with the reference sheets when a slot is left, so the keyframe follows the composition. Internal to the pipeline: it is not a step and nobody edits it.
_Avoid_: shape storyboard, thumbnail, previs, animatic

**Reference sheet**:
The generated picture of one character, or the establishing picture of one place, that every keyframe copies. One candidate is chosen per character.
_Avoid_: model sheet, character card

**Reference photo**:
A photo the person uploads of a real character or place, given to the image model when it draws the reference sheet.

**Scene**:
One shot of the film, S01, S02 and so on, with its picture, voice and motion. storyboard.json calls it a shot.
_Avoid_: clip (a clip is the bought video), segment (a piece of the edit)

**Keyframe**:
The still picture of a scene, drawn from its prompt and the approved reference sheets.
_Avoid_: still image, frame (except in the sketch)

**Motion mode**:
How a scene moves: still, Ken Burns and parallax are free; full motion, in-between, masked motion and cinemagraph (a masked loop) each buy one clip.
_Avoid_: animation type, effect

**Clip**:
A short video bought from a video engine for a scene with a paid motion mode.

**Engine**:
The hosted model that makes a clip or the score, with its price.
_Avoid_: provider (that is the company), backend

**Preview**:
One scene as it will play in the final cut, small and with its voice.

**Final cut**:
The finished film: the approved scenes in order, captions, the score ducked under the voice, and the AI end card, in 9:16 and 16:9.
_Avoid_: export, render, master

**Look**:
The film's visual style: one style text added to every picture prompt, plus one colour grade applied to every scene.
_Avoid_: theme, filter

## Money

**Budget**:
The most the whole film may spend on clips, at list price. Scenes can only choose modes that keep the film inside it.

**Paid action**:
Anything that spends money: buying a clip or the score. It always shows its price and asks first.
