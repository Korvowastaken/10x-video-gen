// Typed calls to the studio API (pipeline/studio.py).

/** Free voice tuning, applied to the saved take (pipeline/tuning.py). A missing field is "as recorded". */
export type Tune = { speed?: number; pitch?: number; age?: number }
export type Line = { speaker: string; text: string; en: string; direction?: string; tune?: Tune }
export type Motion = {
  mode: string
  prompt: string
  seed?: number
  clip_s?: number
  subject?: string
  loop?: string
  engine?: string
  mask?: { target?: string; regions?: unknown[]; feather?: number; align?: boolean }
  end_keyframe?: { prompt: string; seed: number }
  parallax?: { move?: string; amount?: number }
  kenburns?: string
}
export type Shot = {
  id: string
  beat: string
  reason: string
  size: string
  location: string
  characters: string[]
  duration_s: number
  keyframe: { prompt: string; seed: number }
  motion: Motion
  lines: Line[]
  music_cue?: string
}
export type Character = {
  id: string
  name: string
  role: string
  visible: boolean
  real_person: boolean
  consent?: string
  look?: string
  reference?: { prompt: string; seeds: number[]; chosen?: number; photo?: string }
  voice: { name: string; direction: string; tune?: Tune }
}
export type Place = { id: string; name: string; look: string; reference?: { prompt: string; seeds: number[]; photo?: string } }
export type Storyboard = {
  title: string
  logline: string
  language: { name: string }
  characters: Character[]
  locations: Place[]
  shots: Shot[]
  music: { caption: string; seeds: number[]; chosen: number | null; chosen_reason?: string }
  audience: { who: string; where: string; feel: string }
  video?: { budget_usd?: number; allowed_modes?: string[]; max_paid_clips?: number }
  edit?: { use?: Record<string, string> }
}
export type ShotState = {
  id: string
  keyframe: string | null
  end: string | null
  clip: string | null
  paid: boolean
  price: number
  used: string | null
  /** Made from other inputs than the storyboard holds now: a redo would remake it. */
  stale: { keyframe: boolean; voice: boolean[]; clip: boolean }
  lines: {
    audio: string | null
    cer: number | null
    heard: string | null
    seconds: number | null
    /** The tuning the line is rendered with: the character's default, then the line's own. */
    tune: Tune
    /** The tuning the line's current file was rendered with. */
    applied: Tune
    /** A saved take exists for the line's words and voice, so it can be re-tuned for free. */
    tunable: boolean
    /** Some saved take exists, maybe an out-of-date one: settings can be tried on it. */
    previewable: boolean
  }[]
}
/** A free tier's state today: used up or not, when it comes back, and how much is left (when measurable). */
export type Limit = {
  label: string
  used_up: boolean
  resets_at: string
  left: number | null
  /** The same, per saved key (by fingerprint). */
  keys?: Record<string, { used_up: boolean; left?: number }>
}
/** One service's saved keys, masked: a key itself never reaches the browser. */
export type KeyService = {
  id: "gemini" | "cloudflare" | "wavespeed" | "kaggle" | "anthropic" | "azure" | "groq" | "cerebras" | "openrouter"
  label: string
  paid: boolean
  /** Only one key: the service reads it directly, so there is nothing to switch to. */
  single: boolean
  url: string
  for: string
  limit: string
  fields: { name: string; label: string }[]
  keys: { slot: number; n: number; active: boolean; fingerprint: string; masked: Record<string, string> }[]
}
export type LimitId = "writing" | "voices" | "pictures"
/** Consent for real people (pipeline/consent.py). */
export type ConsentStatus = "fictional" | "agreed" | "needs consent" | "withdrawn"
export type ConsentCharacter = {
  id: string
  name: string
  role: string
  visible: boolean
  voice?: string
  real_person: boolean
  consent?: string
  status: ConsentStatus
  lines: { shot: string; text: string; en: string }[]
  /** They agreed to other words than these: they hear the new lines first. */
  lines_changed: boolean
}
export type ConsentRecord = { id: string; character: string; person: string; status: "agreed" | "withdrawn" | "fictional"; self: boolean; how: string; evidence: string; date: string; withdrawn?: string }
export type Consent = { characters: ConsentCharacter[]; records: ConsentRecord[]; wording: { label: string; note: string; text: string }[] }
export type ConsentConfirm = { character: string; self: boolean; read_out: boolean; agreed: boolean; recording_kept: boolean; how: string; evidence: string }
/** One story: its own film in its own folder (pipeline/stories.py). */
export type StoryItem = { id: string; name: string; current: boolean; written: boolean; drafted: boolean }
/** What a revision job hands back: the proposal to review, what is still wrong with it, and who wrote it. */
export type Revision<T> = { proposal: T; errors: string[]; model: string }
/** One model call a job made: which service and model, for what, how it went, how long, what it cost. */
export type CallInfo = { stage: string; item: string; provider: string; model: string; status: "ok" | "error" | "stopped"; seconds?: number; usd?: number; attempt?: number; error?: string }
/** One line of a job's log, `at` seconds after it started (pipeline/jobs.py). */
export type LogEntry = { at: number; level: "info" | "warn" | "error" | "call" | "done"; text: string; call?: CallInfo }
export type Job = {
  id: string
  kind: string
  status: "running" | "done" | "error" | "cancelled"
  log: LogEntry[]
  error?: string
  /** Seconds since 1970, from the studio's clock. */
  started: number
  ended?: number
  /** Stop was asked for; the job ends at its next safe point. */
  stopping?: boolean
  /** The job is waiting: a service ran out or failed, and the next one in line needs a yes (pipeline/switch.py). */
  question?: { from: string; to: string; reason: string; what: string; note: string }
  totals?: { calls: number; failed: number; usd: number }
  /** What the job made, for jobs that hand something back (a revision's proposal). */
  result?: unknown
  /** The stage of the last model call. */
  step?: string
}
export type State = {
  story: string
  /** story.md changed since the storyboard was drafted from it. */
  story_changed?: boolean
  storyboard: Storyboard | null
  errors: string[]
  shots: ShotState[]
  sheets: Record<string, (string | null)[]>
  sheets_stale: Record<string, boolean>
  photos: Record<string, string | null>
  film: { vertical: string | null; wide: string | null; radio: string | null; rough: string | null; report: Record<string, unknown>; stale?: boolean }
  music: (string | null)[]
  /** What a music run would spend now: only candidates not made yet are bought. */
  music_price: number
  limits?: Record<LimitId, Limit>
  spent: number
  calls: number
  jobs: Job[]
}

/** The six steps, from pipeline/flow.py. "final" is the final cut. */
export type FlowStepId = "story" | "script" | "references" | "scenes" | "final"
export type FlowState = "approved" | "stale" | "todo"
export type FlowStep = {
  id: FlowStepId
  title: string
  state: FlowState
  /** What changed since the approval, in words ("the script"). */
  changed: string[]
  locked: boolean
  /** What has to happen before it can be approved. */
  blockers: string[]
}
export type FlowScene = {
  id: string
  state: FlowState
  changed: string[]
  blockers: string[]
  clip_bought: boolean
  price: number
  preview: string | null
  used: string | null
  history: { at: string; mode: string; hash: string }[]
}
export type Settings = { language: string; look: string; target_seconds: number; audience: string; feel: string; [k: string]: unknown }
export type ModeInfo = { label: string; paid: boolean; about: string; usd: number }
export type Flow = {
  steps: FlowStep[]
  scenes: FlowScene[]
  current: FlowStepId | null
  errors: string[]
  budget: { budget_usd: number; planned_usd: number; to_buy_usd: number; spent_usd: number; music_usd: number; allowed_modes: string[] } | null
  settings: Settings
  story_text: string
  catalog: {
    modes: Record<string, ModeInfo>
    engines: Record<string, { provider: string; clip_s: number[]; usd: Record<string, number> }>
    default_engine: string
    music_usd: number | null
  }
}
export type Choices = { languages: Record<string, string>; looks: string[]; defaults: Settings }

export class ApiError extends Error {
  errors: string[]
  constructor(message: string, errors: string[] = []) {
    super(message)
    this.errors = errors
  }
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { "Content-Type": "application/json" }
  }
  const res = await fetch(url, init)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = data?.detail
    const errors: string[] = Array.isArray(detail?.errors) ? detail.errors : []
    throw new ApiError(typeof detail === "string" ? detail : errors[0] ?? `HTTP ${res.status}`, errors)
  }
  return data as T
}

export const api = {
  state: () => call<State>("GET", "/api/state"),
  job: (id: string) => call<Job>("GET", `/api/jobs/${id}`),
  stopJob: (id: string) => call<Job>("POST", `/api/jobs/${id}/stop`),
  answerJob: (id: string, use: boolean) => call<Job>("POST", `/api/jobs/${id}/answer`, { use }),
  saveStory: (text: string) => call("PUT", "/api/story", { text }),
  run: (stage: string, body: Record<string, unknown> = {}) => call<Job>("POST", `/api/run/${stage}`, body),
  saveShot: (shot: Shot) => call("PUT", `/api/shots/${shot.id}`, shot),
  saveCharacter: (c: Character) => call("PUT", `/api/characters/${c.id}`, c),
  savePlace: (p: Place) => call("PUT", `/api/places/${p.id}`, p),
  /** Redo parts of a scene from the scene panel, as one job: save the edits, let the writer rewrite the
   * chosen parts from the note, then remake them. The finished job's result says what the note changed. */
  redoScene: (
    id: string,
    body: { parts: string[]; shot?: Shot; voices?: Record<string, Tune | null>; note?: string; confirm_usd?: number },
  ) => call<Job>("POST", `/api/scenes/${id}/redo`, body),
  previewVoice: (item: string, tune: Tune) => call<{ audio: string; seconds: number; older: boolean }>("POST", "/api/voice/preview", { item, tune }),
  tuneVoices: (body: { characters?: Record<string, Tune | null>; lines?: Record<string, Tune | null> }) => call<Job>("PUT", "/api/voice", body),
  upload: (owner: string, file: File) => {
    const form = new FormData()
    form.append("file", file)
    return call("POST", `/api/references/${owner}`, form)
  },
  removePhoto: (owner: string) => call("DELETE", `/api/references/${owner}`),
  chooseMusic: (chosen: number, reason: string) => call("PUT", "/api/music", { chosen, reason }),
  flow: () => call<Flow>("GET", "/api/flow"),
  choices: () => call<Choices>("GET", "/api/choices"),
  approve: (step: FlowStepId, scene?: string) => call<Flow>("POST", "/api/approve", { step, scene }),
  unapprove: (step: FlowStepId, scene?: string) => call<Flow>("POST", "/api/unapprove", { step, scene }),
  saveSettings: (s: Partial<Settings>) => call("PUT", "/api/settings", s),
  saveStoryText: (text: string) => call("PUT", "/api/story/text", { text }),
  draftScript: () => call<Job>("POST", "/api/script/draft"),
  /** A script revision, run as a job: the finished job's result is a Revision<Storyboard>. */
  reviseScript: (text: string) => call<Job>("POST", "/api/script/revise", { text }),
  acceptScript: (proposal: Storyboard) => call("PUT", "/api/script", proposal),
  reorder: (order: string[]) => call("POST", "/api/scenes/order", { order }),
  drawSheets: () => call<Job>("POST", "/api/sheets/draw"),
  anotherSheet: (owner: string) => call("POST", `/api/sheets/${owner}/another`),
  setVideo: (v: { allowed_modes?: string[]; budget_usd?: number }) => call("PUT", "/api/video", v),
  /** Make several scenes in one free job, in film order. Nothing is bought. */
  makeScenes: (ids: string[]) => call<Job>("POST", "/api/scenes/make", { scenes: ids }),
  makeScene: (id: string, body: { redo?: string[]; buy?: boolean; confirm_usd?: number } = {}) => call<Job>("POST", `/api/scenes/${id}/make`, body),
  restoreScene: (id: string, version: number) => call("POST", `/api/scenes/${id}/restore`, { version }),
  setCut: (use: Record<string, string>) => call("PUT", "/api/cut", { use }),
  makeCut: () => call<Job>("POST", "/api/cut"),
  keys: () => call<KeyService[]>("GET", "/api/keys"),
  addKey: (service: string, values: Record<string, string>) => call("POST", `/api/keys/${service}`, { values }),
  removeKey: (service: string, slot: number) => call("DELETE", `/api/keys/${service}/${slot}`),
  useKey: (service: string, slot: number) => call("POST", `/api/keys/${service}/${slot}/use`),
  consent: () => call<Consent>("GET", "/api/consent"),
  confirmConsent: (body: ConsentConfirm) => call<Consent>("POST", "/api/consent", body),
  /** The Real person switch, turned on: nothing of them is made until consent is confirmed. */
  markRealPerson: (character: string) => call<Consent>("POST", "/api/consent/real", { character }),
  withdrawConsent: (id: string) => call<Consent>("POST", `/api/consent/${id}/withdraw`),
  notRealPerson: (id: string) => call<Consent>("POST", `/api/consent/${id}/fictional`),
  stories: () => call<StoryItem[]>("GET", "/api/stories"),
  newStory: (name: string) => call<StoryItem[]>("POST", "/api/stories", { name }),
  openStory: (id: string) => call<StoryItem[]>("PUT", "/api/stories/current", { id }),
  renameStory: (id: string, name: string) => call<StoryItem[]>("PUT", `/api/stories/${id}`, { name }),
}

export const MODES: Record<string, { label: string; paid: boolean }> = {
  full_i2v: { label: "Full motion", paid: true },
  flf_inbetween: { label: "In-between", paid: true },
  masked_i2v: { label: "Masked motion", paid: true },
  cinemagraph: { label: "Cinemagraph", paid: true },
  parallax: { label: "Parallax", paid: false },
  still_kenburns: { label: "Ken Burns", paid: false },
  still: { label: "Still", paid: false },
}

/** Field-by-field differences between two scenes or storyboards. */
export function diff(a: unknown, b: unknown, path = ""): { path: string; before: string; after: string }[] {
  if (JSON.stringify(a) === JSON.stringify(b)) return []
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) === !Array.isArray(b)) {
    const keys = new Set([...Object.keys(a as object), ...Object.keys(b as object)])
    return [...keys].flatMap((k) =>
      diff((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k], path ? `${path}.${k}` : k),
    )
  }
  const show = (v: unknown) => (v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v))
  return [{ path, before: show(a), after: show(b) }]
}
