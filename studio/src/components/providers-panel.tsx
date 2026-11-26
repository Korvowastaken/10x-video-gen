import { useEffect, useState } from "react"
import { toast } from "sonner"

import type { Studio } from "@/App"
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select"
import { back, usd } from "@/lib/progress"
import { useModels } from "@/lib/models"
import { modelsApi, providersApi, usable, type Models, type ProviderKey, type Providers, type Purpose, type PurposeInfo, type TaskInfo } from "@/lib/providers"
import { cn } from "@/lib/utils"

/** Services billed per use: they have no free limit to report. */
const PAID_SERVICES = new Set(["anthropic", "wavespeed"])

type Tone = "ok" | "out" | "paid" | "none"


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
  const [models, setModels] = useState<Models | null>(null)
  // Look again whenever the studio state changes: after a job, a limit may be used up or a balance spent.
  useEffect(() => {
    let live = true
    providersApi
      .get()
      .then((d) => live && setData(d))
      .catch(() => live && setData(null))
    modelsApi
      .get()
      .then((m) => live && setModels(m))
      .catch(() => live && setModels(null))
    return () => {
      live = false
    }
  }, [studio.state])
  async function reload() {
    const [d, m] = await Promise.all([providersApi.get(), modelsApi.get()])
    setData(d)
    setModels(m)
  }
  return [data, models, reload] as const
}

/** A model picker for one task: the connected services' models first, grouped by service,
 * then the ones whose service has no key yet (greyed, so it's clear what connecting would add). */
function ModelPicker({ task, info, onPick }: { task: string; info: TaskInfo; onPick: (task: string, id: string) => void }) {
  const ready = info.options.filter((o) => o.connected && !o.paused)
  const groups = [...new Set(ready.map((o) => o.provider))].map((p) => ({ provider: p, options: ready.filter((o) => o.provider === p) }))
  const unavailable = info.options.filter((o) => !o.connected || o.paused)
  const fallbacks = info.chain.filter((id) => id !== info.model).map((id) => info.options.find((o) => o.id === id)?.label ?? id)
  return (
    <Select items={info.options.map((o) => ({ value: o.id, label: o.label }))} value={info.model} onValueChange={(v) => v && v !== info.model && onPick(task, String(v))}>
      <SelectTrigger
        size="sm"
        title={`${info.does}.${fallbacks.length ? ` If it can't answer: ${fallbacks.join(", ")}.` : ""}`}
        className="h-6 gap-1 border-none px-1.5 text-[12px] shadow-none hover:bg-secondary"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent className="max-h-96 min-w-96">
        {groups.map((g) => (
          <SelectGroup key={g.provider}>
            <SelectLabel>{g.provider}</SelectLabel>
            {g.options.map((o) => (
              <SelectItem key={o.id} value={o.id} title={o.note || undefined}>
                {o.label}
                <span className={cn("ml-auto pl-3 text-[11px]", o.paid ? "text-paid" : "text-free")}>{o.price}</span>
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
        {unavailable.length > 0 && (
          <SelectGroup>
            <SelectLabel>Not connected or paused</SelectLabel>
            {unavailable.map((o) => (
              <SelectItem key={o.id} value={o.id} disabled>
                {o.label}
                <span className="ml-auto pl-3 text-[11px] text-subtle">{o.paused ? `${o.provider} paused` : `Connect ${o.provider}`}</span>
              </SelectItem>
            ))}
          </SelectGroup>
        )}
      </SelectContent>
    </Select>
  )
}

/** The model a task starts with, its picker's data, and a way to pick: for a picker beside an action. */
export function useTaskModel(studio: Studio, task: string) {
  const [models, setModels] = useModels(studio)
  const info = models?.tasks[task] ?? null
  const chosen = info?.options.find((o) => o.id === info.model) ?? null
  async function pick(t: string, id: string) {
    await chooseModel(t, info!, id)
    setModels(await modelsApi.get())
    await studio.refresh()
  }
  return { info, chosen, pick }
}

async function chooseModel(task: string, info: TaskInfo, id: string) {
  const label = info.options.find((o) => o.id === id)?.label ?? id
  try {
    await modelsApi.choose(task, id)
    toast.success(`${info.label} now start${info.label.endsWith("s") ? "" : "s"} with ${label}`, {
      description: task === "tts" ? "Every line is recorded again with it the next time voices run." : task === "image" ? "Pictures made with the old model show as out of date." : undefined,
    })
  } catch (err) {
    toast.error((err as Error).message)
    throw err
  }
}

/** A labelled model picker for one task, to sit beside the button that runs it. */
export function TaskPicker({ studio, task, label }: { studio: Studio; task: string; label?: string }) {
  const { info, pick } = useTaskModel(studio, task)
  if (!info) return null
  return (
    <span className="inline-flex items-center gap-1 text-[12px]">
      <span className="text-subtle">{label ?? "Model"}:</span>
      <ModelPicker task={task} info={info} onPick={(t, id) => pick(t, id).catch(() => {})} />
    </span>
  )
}

/** One quiet line on a step: a model picker for each task the step runs, and whether its service can run now. */
export function ProvidersPanel({ studio, step }: { studio: Studio; step: string }) {
  const [data, models, reload] = useProviders(studio)
  const tasks = models?.steps[step] ?? []
  if (!tasks.length || !data || !models) return null

  async function pick(task: string, id: string) {
    try {
      await chooseModel(task, models!.tasks[task], id)
    } catch {
      return
    }
    await reload()
    await studio.refresh() // prices and out-of-date marks follow the model
  }

  // The service status shows once per kind of work, after its last task (Storyboard and Lines share Writing's),
  // and only for a task that starts on that service: a Gemini limit says nothing about a Groq model.
  const onService = (t: string) => usable(models.tasks[t])[0]?.service === data[models.tasks[t].purpose as Purpose]?.service
  const lastOfPurpose = new Map(tasks.filter(onService).map((t) => [models.tasks[t].purpose, t]))
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[12px]">
      {tasks.map((t) => {
        const info = models.tasks[t]
        const purpose = data[info.purpose as Purpose]
        return (
          <span key={t} className="inline-flex items-center gap-1.5">
            <span className="text-subtle">{info.label}:</span>
            <ModelPicker task={t} info={info} onPick={pick} />
            {purpose && lastOfPurpose.get(info.purpose) === t && <StatusText info={purpose} />}
          </span>
        )
      })}
      <button className="text-link hover:underline" onClick={() => studio.go("keys")}>
        Connections
      </button>
    </div>
  )
}
