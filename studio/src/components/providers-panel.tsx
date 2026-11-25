import { ChevronDown } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import type { Studio } from "@/App"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { back, usd } from "@/lib/progress"
import { providersApi, STEP_PURPOSES, type ProviderKey, type Providers, type Purpose, type PurposeInfo } from "@/lib/providers"
import { cn } from "@/lib/utils"
import { StatusDot } from "@/views/parts"

const ADD = "add"
const DEFAULT = "default"

/**
 * "Providers and keys" for one step: for each kind of work the step runs, the provider (with a
 * choice where there is one), the key it starts with, and what is left on that key today.
 */
export function ProvidersPanel({ studio, step }: { studio: Studio; step: string }) {
  const purposes = STEP_PURPOSES[step] ?? []
  const [data, setData] = useState<Providers | null>(null)
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem("providers-open") !== "0"
    } catch {
      return true
    }
  })
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

  if (!purposes.length) return null
  const toggle = () => {
    setOpen(!open)
    try {
      localStorage.setItem("providers-open", open ? "0" : "1")
    } catch {
      /* not remembered */
    }
  }
  const reload = async () => setData(await providersApi.get())
  const trouble = data ? purposes.filter((p) => data[p].keys.length === 0 || data[p].keys.every((k) => k.used_up)) : []

  return (
    <section className="mb-7 rounded-lg border">
      <button onClick={toggle} className="flex w-full items-center gap-3 px-4 py-2.5 text-left">
        <span className="text-[13px] font-medium">Providers and keys</span>
        {data && !open && (
          <span className="truncate text-[12px] text-subtle">
            {purposes.map((p) => `${data[p].label} on ${data[p].provider}`).join(" · ")}
          </span>
        )}
        {trouble.length > 0 && <StatusDot status="stale">{trouble.map((p) => data![p].label).join(", ")} can't run now</StatusDot>}
        <ChevronDown className={cn("ml-auto size-4 text-subtle transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="border-t">
          {!data && <p className="px-4 py-3 text-[12.5px] text-subtle">Reading providers…</p>}
          {data && (
            <div className="divide-y">
              {purposes.map((p) => (
                <Row key={p} purpose={p} info={data[p]} studio={studio} onChange={reload} />
              ))}
            </div>
          )}
          <p className="border-t px-4 py-2 text-[12px] text-subtle">
            When a key runs out mid-run, the next saved key for the same provider takes over by itself.{" "}
            <button className="text-primary hover:underline" onClick={() => studio.go("keys")}>
              Manage keys
            </button>
          </p>
        </div>
      )}
    </section>
  )
}

function Row({ purpose, info, studio, onChange }: { purpose: Purpose; info: PurposeInfo; studio: Studio; onChange: () => Promise<void> }) {
  const current = info.keys.find((k) => k.slot === info.starts)
  const engine = info.engines.find((e) => e.id === info.engine)

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

  async function setKey(value: string) {
    if (value === ADD) return studio.go("keys")
    try {
      await providersApi.chooseKey(purpose, value === DEFAULT ? null : Number(value))
      await onChange()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const keyItems = [
    ...info.keys.map((k) => ({ value: String(k.slot), label: `Key ${k.n} ${k.masked}` })),
    { value: ADD, label: "Add a key…" },
  ]
  return (
    <div className="grid grid-cols-[200px_220px_170px_minmax(0,1fr)] items-center gap-4 px-4 py-2.5">
      <div className="min-w-0">
        <div className="text-[13px] font-medium">{info.label}</div>
        <div className="line-clamp-2 text-[12px] leading-snug text-subtle" title={info.does}>
          {info.does}
        </div>
      </div>

      {info.engines.length > 1 ? (
        <Select
          items={info.engines.map((e) => ({ value: e.id, label: e.label }))}
          value={info.engine ?? ""}
          onValueChange={(v) => v && v !== info.engine && setEngine(String(v))}
        >
          <SelectTrigger size="sm" className="w-full" title={engine?.note || undefined}>
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
        <span className="text-[13px] text-secondary-foreground">{info.provider}</span>
      )}

      {info.keys.length === 0 ? (
        <button className="justify-self-start text-[12.5px] text-primary hover:underline" onClick={() => studio.go("keys")}>
          Add a {info.provider} key
        </button>
      ) : info.keys.length === 1 || info.single ? (
        <span className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          Key 1 <span className="font-mono text-[12px]">{info.keys[0].masked}</span>
          {!info.single && (
            <button className="text-[12px] text-primary hover:underline" onClick={() => studio.go("keys")}>
              Add
            </button>
          )}
        </span>
      ) : (
        <Select items={keyItems} value={String(info.starts ?? "")} onValueChange={(v) => v && setKey(String(v))}>
          <SelectTrigger size="sm" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {keyItems.map((k) => (
              <SelectItem key={k.value} value={k.value}>
                {k.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      <div className="min-w-0 text-right">
        {engine?.provider === "kaggle" && !current && <span className="text-[12px] text-subtle">{engine.note}</span>}
        {current && <Left purpose={purpose} info={info} k={current} others={info.keys.filter((k) => k !== current && !k.used_up).length} />}
      </div>
    </div>
  )
}

/** What is left on the key this work starts with. */
function Left({ purpose, info, k, others }: { purpose: Purpose; info: PurposeInfo; k: ProviderKey; others: number }) {
  const spare = others > 0 ? ` · ${others} more key${others > 1 ? "s" : ""} ready` : ""
  if (info.service === "wavespeed") {
    if (k.balance_usd == null) return <span className="text-[12px] text-subtle">Balance unknown (WaveSpeed did not answer)</span>
    return (
      <StatusDot status={k.used_up ? "stale" : "paid"}>
        {usd(k.balance_usd)} balance{k.used_up ? ", too low for a clip" : ""}
        {spare}
      </StatusDot>
    )
  }
  if (info.service === "kaggle") {
    if (k.hours_left == null) return <span className="text-[12px] text-subtle">GPU time unknown</span>
    const refill = k.resets_at ? new Date(k.resets_at.replace(" ", "T") + "Z").toLocaleDateString([], { weekday: "short" }) : null
    return (
      <StatusDot status={k.used_up ? "stale" : "ok"}>
        {k.hours_left} GPU h left this week{refill ? `, refills ${refill}` : ""}
      </StatusDot>
    )
  }
  if (k.used_up)
    return (
      <StatusDot status="stale">
        Used up, back {k.resets_at ? back({ label: "", used_up: true, resets_at: k.resets_at, left: null }).time : "tomorrow"}
        {spare}
      </StatusDot>
    )
  return (
    <StatusDot status="ok">
      {purpose === "pictures" && k.left != null ? `~${k.left} pictures left today` : "Free limit available today"}
      {spare}
    </StatusDot>
  )
}
