// Typed calls to the studio API (pipeline/studio.py).

export type Line = { speaker: string; text: string; en: string; direction?: string }
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
  voice: { name: string; direction: string }
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
  lines: { audio: string | null; cer: number | null; heard: string | null; seconds: number | null }[]
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
  id: "gemini" | "cloudflare" | "wavespeed" | "kaggle"
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
export type Job = { id: string; kind: string; status: "running" | "done" | "error"; log: string[]; error?: string }
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
  saveStory: (text: string) => call("PUT", "/api/story", { text }),
  run: (stage: string, body: Record<string, unknown> = {}) => call<Job>("POST", `/api/run/${stage}`, body),
  saveShot: (shot: Shot) => call("PUT", `/api/shots/${shot.id}`, shot),
  saveCharacter: (c: Character) => call("PUT", `/api/characters/${c.id}`, c),
  feedback: (id: string, text: string) =>
    call<{ proposal: Shot; errors: string[]; model: string }>("POST", `/api/shots/${id}/feedback`, { text }),
  redo: (id: string, parts: string[]) => call<Job>("POST", `/api/shots/${id}/redo`, { parts }),
  upload: (owner: string, file: File) => {
    const form = new FormData()
    form.append("file", file)
    return call("POST", `/api/references/${owner}`, form)
  },
  removePhoto: (owner: string) => call("DELETE", `/api/references/${owner}`),
  chooseMusic: (chosen: number, reason: string) => call("PUT", "/api/music", { chosen, reason }),
  keys: () => call<KeyService[]>("GET", "/api/keys"),
  addKey: (service: string, values: Record<string, string>) => call("POST", `/api/keys/${service}`, { values }),
  removeKey: (service: string, slot: number) => call("DELETE", `/api/keys/${service}/${slot}`),
  useKey: (service: string, slot: number) => call("POST", `/api/keys/${service}/${slot}/use`),
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

/** Field-by-field differences between two scenes, for the feedback review. */
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
