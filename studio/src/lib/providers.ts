// Which provider and key each kind of work uses, and what is left there (pipeline/accounts.py).

import type { LimitId } from "@/api"
import { FREE, type Cost } from "@/lib/progress"

export type Purpose = "writing" | "voices" | "pictures" | "clips" | "music"

export type ProviderKey = {
  slot: number
  n: number
  masked: string
  used_up: boolean
  resets_at?: string | null
  left?: number | null
  balance_usd?: number | null
  hours_left?: number | null
}

export type PurposeInfo = {
  label: string
  does: string
  service: "gemini" | "cloudflare" | "wavespeed" | "kaggle" | "anthropic" | "azure" | "groq" | "cerebras" | "openrouter"
  provider: string
  engine: string | null
  engines: { id: string; label: string; provider: string; price: string; paid: boolean; note: string }[]
  single: boolean
  /** The key chosen for this purpose, or null for the service's default. */
  chosen: number | null
  /** The key the next call starts with. */
  starts: number | null
  keys: ProviderKey[]
}

export type Providers = Record<Purpose, PurposeInfo>

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = data?.detail
    throw new Error(typeof detail === "string" ? detail : detail?.errors?.[0] ?? `HTTP ${res.status}`)
  }
  return data as T
}

/** One model that can do a task (pipeline/catalog.py). */
export type ModelOption = {
  id: string
  label: string
  service: string
  provider: string
  connected: boolean
  paused: boolean
  price: string
  paid: boolean
  note: string
}

export type TaskInfo = {
  label: string
  purpose: Purpose
  does: string
  /** What runs, in order: the first that has a key answers, the rest are fallbacks. */
  chain: string[]
  /** The model that answers first now. */
  model: string
  options: ModelOption[]
}

export type Models = { tasks: Record<string, TaskInfo>; steps: Record<string, string[]> }

export const modelsApi = {
  get: () => call<Models>("GET", "/api/models"),
  choose: (task: string, model: string) => call("PUT", `/api/models/${task}`, { model }),
}

export const providersApi = {
  get: () => call<Providers>("GET", "/api/providers"),
  chooseKey: (purpose: Purpose, slot: number | null) => call("PUT", `/api/providers/${purpose}`, { slot, set_slot: true }),
}

/** The service each daily free limit counts. */
const LIMIT_SERVICE: Record<LimitId, string> = { writing: "gemini", voices: "gemini", pictures: "cloudflare" }

/** The models a task can run on now, in the order it tries them: connected and not paused. */
export const usable = (info: TaskInfo) =>
  info.chain.map((id) => info.options.find((o) => o.id === id)).filter((o): o is ModelOption => !!o && o.connected && !o.paused)

/**
 * The cost of work that runs these tasks, read from the models picked for them: named after the
 * service that answers first, and held back by a free limit only when a task can run nowhere else
 * (a used-up Gemini does not stop a draft that starts on Groq, or that falls back to Claude).
 * While the pickers load, it counts the limit, as before.
 */
export function taskCost(infos: (TaskInfo | null | undefined)[], limit: LimitId): Cost {
  const known = infos.filter((i): i is TaskInfo => !!i)
  if (!known.length) return FREE(undefined, limit)
  const first = usable(known[0])[0]
  const bound = known.some((i) => {
    const can = usable(i)
    return can.length > 0 && can.every((o) => o.service === LIMIT_SERVICE[limit])
  })
  return FREE(first?.provider, bound ? limit : undefined)
}
