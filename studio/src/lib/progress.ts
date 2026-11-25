// Where the film stands: each step's status, each scene's parts, and the one next step.

import { api, diff, MODES, type Job, type Limit, type LimitId, type Shot, type ShotState, type State } from "@/api"

export type StepId = "story" | "references" | "scenes" | "film"
export type StepState = "done" | "todo" | "stale" | "locked"
export type Step = { id: StepId; label: string; state: StepState; note: string }

/** Free work runs at once, within a daily free limit; paid work names its price and is confirmed first. */
export type Cost = { paid: false; via?: string; limit?: LimitId } | { paid: true; usd: number; via: string }
export const FREE = (via?: string, limit?: LimitId): Cost => ({ paid: false, via, limit })
/** The free limit each kind of work draws on. */
export const LIMIT_OF: Record<Part, LimitId | undefined> = { keyframe: "pictures", voice: "voices", clip: undefined }

/** When a used-up limit comes back, in the viewer's time.
 *  time: "11 AM" for tags; text: "tomorrow at 11 AM (in 14 h 22 min)" for sentences. */
export function back(limit: Limit, now = new Date()) {
  const at = new Date(limit.resets_at)
  const mins = Math.max(1, Math.round((at.getTime() - now.getTime()) / 60000))
  const time = at.toLocaleTimeString([], at.getMinutes() ? { hour: "numeric", minute: "2-digit" } : { hour: "numeric" })
  const day = at.toDateString() === now.toDateString() ? "today" : "tomorrow"
  const wait = mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h${mins % 60 ? ` ${mins % 60} min` : ""}`
  return { time, wait: `in ${wait}`, text: `${day} at ${time} (in ${wait})` }
}

export function blocked(cost: Cost, limits: State["limits"]): Limit | null {
  if (cost.paid || !cost.limit || !limits) return null
  const l = limits[cost.limit]
  return l?.used_up ? l : null
}
export const PAID = (usd: number, via = "WaveSpeed"): Cost => ({ paid: true, usd, via })
export const usd = (n: number) => `$${n < 0.1 && n > 0 ? n.toFixed(3).replace(/0$/, "") : n.toFixed(2)}`

export type Part = "keyframe" | "voice" | "clip"
export const PART_LABEL: Record<Part, string> = { keyframe: "Still", voice: "Voice", clip: "Clip" }

export function scene(m: ShotState) {
  const stale: Part[] = []
  if (m.stale.keyframe) stale.push("keyframe")
  if (m.stale.voice.some(Boolean)) stale.push("voice")
  if (m.stale.clip) stale.push("clip")
  const missing: Part[] = []
  if (!m.keyframe) missing.push("keyframe")
  if (m.lines.some((l) => !l.audio)) missing.push("voice")
  return { stale, missing, toBuy: m.paid && !m.clip, needsWork: stale.length > 0 || missing.length > 0 }
}

/** Which parts of a scene an edit makes out of date, read from the changed fields.
 *  A clip counts only when one was bought: there is nothing to go out of date otherwise. */
export function affected(before: Shot, after: Shot, hasClip = true): Part[] {
  const paths = diff(before, after).map((c) => c.path)
  const parts = new Set<Part>()
  const paid = MODES[after.motion.mode]?.paid
  for (const p of paths) {
    if (/^(keyframe|characters|location|size)/.test(p) || p.startsWith("motion.end_keyframe")) parts.add("keyframe")
    if (/^lines\.\d+\.(text|speaker)/.test(p) || /^lines\.\d+$/.test(p) || p === "lines") parts.add("voice")
    if (p.startsWith("motion")) parts.add("clip")
  }
  if (parts.has("keyframe")) parts.add("clip") // a clip is made from the still
  if (!paid || !hasClip) parts.delete("clip")
  return (["keyframe", "voice", "clip"] as Part[]).filter((p) => parts.has(p))
}

const FIELD: Record<string, string> = {
  "keyframe.prompt": "Picture",
  "keyframe.seed": "Picture seed",
  "motion.mode": "Motion type",
  "motion.prompt": "Motion",
  "motion.clip_s": "Clip length",
  "motion.mask.target": "What moves",
  "motion.end_keyframe.prompt": "End frame",
  "motion.parallax.move": "Camera move",
  "motion.kenburns": "Pan or zoom",
  beat: "What happens",
  reason: "Why the film needs it",
  characters: "Cast",
  location: "Place",
  size: "Shot size",
  duration_s: "Length",
  music_cue: "Music cue",
}
const LINE_FIELD: Record<string, string> = { text: "Amharic", en: "English subtitle", speaker: "Speaker", direction: "Delivery" }

export function fieldLabel(path: string) {
  const m = path.match(/^lines\.(\d+)(?:\.(\w+))?/)
  if (m) return `Line ${Number(m[1]) + 1}${m[2] ? ` · ${LINE_FIELD[m[2]] ?? m[2]}` : ""}`
  return FIELD[path] ?? path
}

export function steps(state: State): Step[] {
  const sb = state.storyboard
  if (!sb)
    return [
      { id: "story", label: "Story", state: "todo", note: state.story.trim() ? "Ready to draft scenes" : "Write the story" },
      { id: "references", label: "Look", state: "locked", note: "After the story" },
      { id: "scenes", label: "Scenes", state: "locked", note: "After the story" },
      { id: "film", label: "Film", state: "locked", note: "After the scenes" },
    ]
  const sheets = Object.entries(state.sheets)
  const undrawn = sheets.filter(([, urls]) => urls.some((u) => !u)).length
  const oldSheets = sheets.filter(([id]) => state.sheets_stale?.[id]).length
  const scenes = state.shots.map(scene)
  const staleScenes = scenes.filter((s) => s.stale.length).length
  const unmade = scenes.filter((s) => s.missing.length).length
  const cut = state.film.vertical ?? state.film.rough ?? state.film.radio
  return [
    state.story_changed
      ? { id: "story", label: "Story", state: "stale", note: "Changed since the draft" }
      : { id: "story", label: "Story", state: "done", note: `${sb.shots.length} scenes drafted` },
    undrawn
      ? { id: "references", label: "Look", state: "todo", note: `${undrawn} sheet${undrawn > 1 ? "s" : ""} to draw` }
      : oldSheets
        ? { id: "references", label: "Look", state: "stale", note: `${oldSheets} out of date` }
        : { id: "references", label: "Look", state: "done", note: "Sheets approved" },
    staleScenes
      ? { id: "scenes", label: "Scenes", state: "stale", note: `${staleScenes} need a redo` }
      : unmade
        ? { id: "scenes", label: "Scenes", state: "todo", note: `${unmade} not made yet` }
        : { id: "scenes", label: "Scenes", state: "done", note: `${sb.shots.length} ready` },
    !cut
      ? { id: "film", label: "Film", state: "todo", note: "No cut yet" }
      : state.film.stale
        ? { id: "film", label: "Film", state: "stale", note: "Older than your edits" }
        : { id: "film", label: "Film", state: "done", note: state.film.vertical ? "Final cut made" : "Rough cut made" },
  ]
}

export type Next = {
  step: StepId
  title: string
  detail: string
  label: string
  cost: Cost
  run?: () => Promise<Job>
}

export function next(state: State): Next {
  const sb = state.storyboard
  if (!sb)
    return {
      step: "story",
      title: "Draft the scenes",
      detail: "Gemini reads your story and writes the scenes, lines and pictures.",
      label: "Draft storyboard",
      cost: FREE("Gemini", "writing"),
      run: state.story.trim() ? () => api.run("script", { force: true }) : undefined,
    }
  const scenes = state.shots.map(scene)
  const sheets = Object.entries(state.sheets)
  const sheetWork = sheets.filter(([id, urls]) => urls.some((u) => !u) || state.sheets_stale?.[id]).length
  const stills = scenes.filter((s) => s.stale.includes("keyframe") || s.missing.includes("keyframe")).length
  if (sheetWork || stills) {
    const pictures = state.limits?.pictures
    const wanted =
      sheets.filter(([id, urls]) => urls.some((u) => !u) || state.sheets_stale?.[id]).reduce((n, [, urls]) => n + urls.length, 0) + stills
    const short = pictures && !pictures.used_up && pictures.left != null && pictures.left < wanted
    return {
      step: sheetWork ? "references" : "scenes",
      title: [sheetWork && `${sheetWork} sheet${sheetWork > 1 ? "s" : ""}`, stills && `${stills} still${stills > 1 ? "s" : ""}`]
        .filter(Boolean)
        .join(" and ") + " to redraw",
      detail: short
        ? `About ${wanted} pictures to draw, ${pictures!.left} left in today's free limit. The rest can wait until ${back(pictures!).text}.`
        : "Only what changed is drawn again, from the approved sheets.",
      label: "Redraw",
      cost: FREE("Cloudflare", "pictures"),
      run: () => api.run("keyframes"),
    }
  }
  const voices = state.shots.reduce((n, m) => n + m.lines.filter((l, i) => !l.audio || m.stale.voice[i]).length, 0)
  if (voices)
    return {
      step: "scenes",
      title: `${voices} line${voices > 1 ? "s" : ""} to record`,
      detail: "New voice takes for the lines you changed, checked by listening back.",
      label: "Record",
      cost: FREE("Gemini", "voices"),
      run: () => api.run("narration"),
    }
  const cut = state.film.vertical ?? state.film.rough ?? state.film.radio
  if (!cut || state.film.stale)
    return {
      step: "film",
      title: cut ? "Your cut is older than your edits" : "Watch the film so far",
      detail: "A rough cut puts free motion over the stills, with voice and captions.",
      label: "Make rough cut",
      cost: FREE(),
      run: () => api.run("rough"),
    }
  return {
    step: "scenes",
    title: "Watch, then give feedback",
    detail: "Pick a scene that feels off, say what should change, and redo it.",
    label: "Open scenes",
    cost: FREE(),
  }
}
