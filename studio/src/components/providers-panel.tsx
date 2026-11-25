import { useEffect, useState } from "react"
import { toast } from "sonner"

import type { Studio } from "@/App"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { back, usd } from "@/lib/progress"
import { providersApi, STEP_PURPOSES, type ProviderKey, type Providers, type Purpose, type PurposeInfo } from "@/lib/providers"
import { cn } from "@/lib/utils"

/** Services billed per use: they have no free limit to report. */
const PAID_SERVICES = new Set(["anthropic", "wavespeed"])

type Tone = "ok" | "out" | "paid" | "none"

/** The services a kind of work tries, in order (pipeline/accounts.py "chain"). */
type Link = { service: string; provider: string; connected: boolean }
const chainOf = (info: PurposeInfo): Link[] => (info as PurposeInfo & { chain?: Link[] }).chain ?? [{ service: info.service, provider: info.provider, connected: info.keys.length > 0 }]

/** One short status for a kind of work: what is left on the key it starts with. */
function purposeStatus(info: PurposeInfo): { tone: Tone; text: string } {
  const k: ProviderKey | undefined = info.keys.find((x) => x.slot === info.starts) ?? info.keys[0]
  const spare = info.keys.filter((x) => x !== k && !x.used_up).length
  if (!k) return { tone: "none", text: "No key yet" }
  if (info.service === "wavespeed") {
    if (k.balance_usd == null) return { tone: "paid", text: "Balance unknown" }
    return { tone: k.used_up ? "out" : "paid", text: `${usd(k.balance_usd)} balance${k.used_up ? ", too low" : ""}` }
  }
  if (PAID_SERVICES.has(info.service)) return { tone: "paid", text: "Paid per use" }
  if (info.service === "kaggle") {
    if (k.hours_left == null) return { tone: "ok", text: "GPU time unknown" }
    return { tone: k.used_up ? "out" : "ok", text: `${k.hours_left} GPU h left this week` }
  }
  if (k.used_up) {
    const when = k.resets_at ? back({ label: "", used_up: true, resets_at: k.resets_at, left: null }).time : "tomorrow"
    return { tone: spare ? "ok" : "out", text: spare ? `Key ${k.n} used up, next key ready` : `Used up, back ${when}` }
  }
  if (info.service === "cloudflare" && k.left != null) return { tone: "ok", text: `~${k.left} pictures left` }
  return { tone: "ok", text: "Free today" }
}

const DOT: Record<Tone, string> = { ok: "bg-free", out: "bg-warn", paid: "bg-paid", none: "border border-thread" }
const TEXT: Record<Tone, string> = { ok: "text-muted-foreground", out: "text-warn", paid: "text-muted-foreground", none: "text-subtle" }

export function StatusText({ info }: { info: PurposeInfo }) {
  const s = purposeStatus(info)
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[12px] whitespace-nowrap", TEXT[s.tone])}>
      <span className={cn("size-1.5 shrink-0 rounded-full", DOT[s.tone])} />
      {s.text}
    </span>
  )
}

function useProviders(studio: Studio) {
  const [data, setData] = useState<Providers | null>(null)
  // Look again whenever the studio state changes: after a job, a limit may be used up or a balance spent.
  useEffect(() => {
    let live = true
    providersApi
      .get()
      .then((d) => live && setData(d))
      .catch(() => live && setData(null))
    return () => {
      live = false
    }
  }, [studio.state])
  return [data, async () => setData(await providersApi.get())] as const
}

/** One quiet line on a step: which service does each kind of work here, and whether it can run now. */
export function ProvidersPanel({ studio, step }: { studio: Studio; step: string }) {
  const purposes = STEP_PURPOSES[step] ?? []
  const [data] = useProviders(studio)
  if (!purposes.length || !data) return null
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px]">
      {purposes.map((p) => (
        <span key={p} className="inline-flex items-center gap-1.5">
          <span className="text-subtle">{data[p].label}:</span>
          <span>{data[p].provider}</span>
          <StatusText info={data[p]} />
        </span>
      ))}
      <button className="text-link hover:underline" onClick={() => studio.go("keys")}>
        Connections
      </button>
    </div>
  )
}

/** For the Keys page: each kind of work, the service that does it (with a choice for clips and music), and what is left. */
export function PurposeRows({ studio }: { studio: Studio }) {
  const [data, reload] = useProviders(studio)
  if (!data) return <p className="py-3 text-[13px] text-subtle">Reading services…</p>
  return (
    <div className="divide-y border-y">
      {(Object.keys(data) as Purpose[]).map((p) => (
        <PurposeRow key={p} purpose={p} info={data[p]} studio={studio} onChange={reload} />
      ))}
    </div>
  )
}

function PurposeRow({ purpose, info, studio, onChange }: { purpose: Purpose; info: PurposeInfo; studio: Studio; onChange: () => Promise<void> }) {
  async function setEngine(id: string) {
    try {
      await providersApi.chooseEngine(purpose, id)
      toast.success(`${info.label} now use ${info.engines.find((e) => e.id === id)?.label}`)
      await onChange()
      await studio.refresh() // prices per scene follow the engine
    } catch (err) {
      toast.error((err as Error).message)
    }
  }
  return (
    <div className="grid grid-cols-[180px_260px_minmax(0,1fr)] items-center gap-6 py-3">
      <div className="min-w-0">
        <div className="text-[14px] font-medium">{info.label}</div>
        <div className="truncate text-[12px] text-subtle" title={info.does}>
          {info.does}
        </div>
      </div>
      {info.engines.length > 1 ? (
        <Select items={info.engines.map((e) => ({ value: e.id, label: e.label }))} value={info.engine ?? ""} onValueChange={(v) => v && v !== info.engine && setEngine(String(v))}>
          <SelectTrigger size="sm" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="min-w-80">
            {info.engines.map((e) => (
              <SelectItem key={e.id} value={e.id}>
                {e.label}
                <span className={cn("ml-auto pl-3 text-[11px]", e.paid ? "text-paid" : "text-free")}>{e.price}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px]">
          {chainOf(info).map((c, i) => (
            <span key={c.service} className="inline-flex items-center gap-1.5">
              {i > 0 && <span className="text-subtle">then</span>}
              <span className={cn(!c.connected && "text-subtle")} title={c.connected ? undefined : "No key yet: skipped"}>
                {c.provider}
                {!c.connected && " (no key)"}
              </span>
            </span>
          ))}
        </span>
      )}
      <StatusText info={info} />
    </div>
  )
}
