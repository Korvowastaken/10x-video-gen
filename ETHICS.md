# Ethics: consent, licences, labelling

## Consent records

The pipeline does not generate the face, likeness or voice of a real person
until their consent is recorded. In `storyboard.json` a real person carries
`"real_person": true` and `"consent": "C<n>"`. `make validate`, and every stage
that calls it, fails until that id is confirmed.

Consent is confirmed in the studio, on the Script step's People list: it shows
the request below and the person's lines, asks that they were read out and
agreed to and that the recording is kept, and writes the record to the story's
`consent.json` (who, how they are shown and voiced, the lines they heard, how
the answer was recorded, the date). A withdrawn consent blocks the person
again. Rows in the table below count too, for records written by hand. The
test `tests/test_storyboard.py::test_real_person_without_consent_record_is_blocked`
keeps that rule in place.

| ID | Person | Shown as | Voiced as | What they agreed to | How recorded | Date | Evidence kept |
|---|---|---|---|---|---|---|---|

No rows yet. The current `story.md` is the brief's example story (a girl
walking to the market in Dessie with her mother), used to build and test the
pipeline. All of its characters are fictional composites, so it depicts no real
person and needs no row. The real family story replaces it before the film is
published, and its consent row is added here first.

### How consent is asked

Read this to the person in the language they prefer, play them the lines
their character will speak, and record the answer (a voice note or a short
video on your phone is enough). Keep the recording privately, not in this
repository; write here only that it exists and where.

> **English.** I am making a short film, 60 to 90 seconds, about your story,
> using AI. A cartoon-like 3D character that represents you will appear in it,
> and a computer voice (not your real voice) will say these words in Amharic,
> which I will read to you now. The film will be posted publicly on TikTok and
> YouTube with a label saying it was made with AI. You can say no now, or ask
> me to take it down at any time. Do you agree?

> **Amharic** (my draft; Robel to check the wording).
> ስለ ታሪክዎ ከ60 እስከ 90 ሰከንድ የሚረዝም አጭር ፊልም በአርቴፊሻል ኢንተለጀንስ (AI) እየሰራሁ ነው።
> በፊልሙ ውስጥ እርስዎን የሚወክል የካርቱን ገጸ-ባህሪ ይታያል፤ የእርስዎ ያልሆነ፣ በኮምፒውተር የተሰራ ድምፅም
> እነዚህን ቃላት በአማርኛ ይናገራል። ቃላቱን አሁን አነብልዎታለሁ። ፊልሙ በቲክቶክና በዩቲዩብ ላይ
> "በAI የተሰራ" የሚል ምልክት ተደርጎበት በይፋ ይለጠፋል። አሁን "አልፈልግም" ማለት፣ ወይም በማንኛውም ጊዜ
> እንዲነሳ መጠየቅ ይችላሉ። ይስማማሉ?

Voices are Gemini's prebuilt TTS voices, never a clone of the person. The
words a real person's character speaks are the ones they heard and agreed to;
if a line changes after consent, they hear the new line before it is used.

## Licences

| Part | Model or tool | Licence and terms | Note |
|---|---|---|---|
| Script, subtitles | Gemini 3.5 to 3.8 Flash (Gemini API, free tier) | Gemini API Additional Terms | On the free tier Google may use prompts to improve its products, so `story.md` keeps to first names and no private details |
| Narration | Gemini 3.8 Flash TTS (fallbacks: 3.8 Flash Lite TTS, 2.5 Flash TTS) | Gemini API Additional Terms | Google states Gemini audio carries a SynthID watermark; the pipeline trims and levels the audio but adds no step that strips it |
| Listen-back check | gemini-3.5-transcribe | Gemini API Additional Terms | |
| Keyframes | FLUX.2 [klein] 4B on Cloudflare Workers AI | Apache 2.0 weights; Cloudflare and Black Forest Labs terms of service | The 9B variant is non-commercial and is not used |
| Keyframe fallback | FLUX.1 [schnell] on Workers AI | Apache 2.0 | |
| Moving shots | Wan 2.2 I2V on WaveSpeed AI (fallback: Wan 2.2 TI2V-5B on Kaggle) | Apache 2.0 weights; WaveSpeed AI Terms of Service for the hosted run | WaveSpeed says commercial use depends on the model licence and its terms; checked before publishing |
| Score | ACE-Step 1.5 on WaveSpeed AI (fallback: Kaggle) | MIT, code and weights; WaveSpeed AI Terms of Service | The model card says outputs may be used commercially; trained on licensed, royalty-free and synthetic data |
| Fonts | Noto Sans, Noto Sans Ethiopic | SIL Open Font License 1.1 (`assets/fonts/OFL.txt`) | |
| Assembly | FFmpeg | LGPL/GPL, used as a tool | Not redistributed in this repository |

## Labelling plan

- The film ends on a three-second **"Made with AI"** end card that names the
  models used for pictures, motion, voices and music.
- When posting: switch on TikTok's "AI-generated content" label, YouTube's
  "altered or synthetic content" disclosure, and Instagram's "AI info" label.
  The post says in plain words that the pictures, voices and music are AI-made.
- Provenance: nothing in the pipeline removes watermarks or metadata from
  model outputs.
- Style: prompts describe qualities (low-poly 3D, warm lamp light, bokeh),
  never a living artist's name. The look follows the reference TikTok's
  general style with original characters, not its characters.
