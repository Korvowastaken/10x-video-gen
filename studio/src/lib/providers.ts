// Which provider and key each kind of work uses, and what is left there (pipeline/accounts.py).

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

/** The work each step runs; steps without provider calls (Story, Sketch) have none. */
export const STEP_PURPOSES: Record<string, Purpose[]> = {
  script: ["writing"],
  references: ["pictures"],
  scenes: ["writing", "voices", "pictures", "clips"],
  film: ["voices", "clips", "music"],
}

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

export const providersApi = {
  get: () => call<Providers>("GET", "/api/providers"),
  chooseKey: (purpose: Purpose, slot: number | null) => call("PUT", `/api/providers/${purpose}`, { slot, set_slot: true }),
  chooseEngine: (purpose: Purpose, engine: string) => call("PUT", `/api/providers/${purpose}`, { engine }),
}
