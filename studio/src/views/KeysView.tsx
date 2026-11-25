import { ExternalLink, Plus, Search, X } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"

import { api, type KeyService } from "@/api"
import type { Studio } from "@/App"
import { ServiceLogo } from "@/components/service-logo"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import { Page } from "@/views/parts"

/** What /api/keys returns per service, plus the pause switch (pipeline/paused.py). */
type Service = KeyService & { pausable?: boolean; paused?: boolean }
type Key = KeyService["keys"][number]

/** The side list: the kinds of work. A service can do more than one (Gemini writes and speaks). */
const GROUPS: { id: string; title: string; ids: string[] }[] = [
  { id: "writing", title: "Writing", ids: ["anthropic", "gemini", "groq", "cerebras", "openrouter"] },
  { id: "video", title: "Video", ids: ["wavespeed", "kaggle"] },
  { id: "voice", title: "Voice", ids: ["azure", "gemini"] },
  { id: "pictures", title: "Pictures", ids: ["cloudflare"] },
  { id: "sound", title: "Sound", ids: ["wavespeed", "kaggle"] },
]
const FILTERS = [
  { id: "all", label: "All" },
  { id: "on", label: "Connected" },
  { id: "off", label: "Not connected" },
] as const

async function setPaused(service: string, paused: boolean) {
  const res = await fetch(`/api/keys/${service}/paused`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paused }) })
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail ?? `HTTP ${res.status}`)
}

export function KeysView({ studio }: { studio: Studio }) {
  const [services, setServices] = useState<Service[] | null>(null)
  const [group, setGroup] = useState("all")
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all")
  const [query, setQuery] = useState("")
  const [open, setOpen] = useState<string | null>(null)
  const load = useCallback(async () => {
    try {
      setServices((await api.keys()) as Service[])
    } catch (err) {
      toast.error(`Could not read the connections: ${(err as Error).message}`)
    }
  }, [])
  useEffect(() => {
    load()
  }, [load])
  const changed = async () => {
    await load()
    await studio.refresh()
  }

  const all = services ?? []
  const inGroup = (s: Service, id: string) => GROUPS.find((x) => x.id === id)!.ids.includes(s.id)
  const q = query.trim().toLowerCase()
  const shown = all.filter(
    (s) =>
      (group === "all" || inGroup(s, group)) &&
      (filter === "all" || (filter === "on") === s.keys.length > 0) &&
      (!q || `${s.label} ${s.for}`.toLowerCase().includes(q)),
  )
  const current = all.find((s) => s.id === open) ?? null

  return (
    <Page className="max-w-6xl">
      <header className="mb-6">
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em]">Connections</h1>
        <p className="mt-1 max-w-2xl text-muted-foreground">
          The services that write, speak, draw and move your film. Keys stay in the .env file on this computer; when a free limit runs out, the next key takes over.
        </p>
      </header>

      <div className="grid grid-cols-[200px_minmax(0,1fr)] gap-8">
        <nav aria-label="Categories" className="sticky top-6 flex flex-col gap-0.5 self-start">
          <SideItem active={group === "all"} onClick={() => setGroup("all")} label="All services" n={all.length} />
          {GROUPS.map((g) => (
            <SideItem key={g.id} active={group === g.id} onClick={() => setGroup(g.id)} label={g.title} n={all.filter((s) => inGroup(s, g.id)).length} />
          ))}
        </nav>

        <div className="min-w-0">
          <div className="sticky top-0 z-10 -mt-6 mb-1 flex items-center gap-2 bg-background pt-6 pb-4">
            <div role="radiogroup" aria-label="Show" className="flex gap-1">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  role="radio"
                  aria-checked={filter === f.id}
                  onClick={() => setFilter(f.id)}
                  className={cn(
                    "h-7 rounded-full border px-3 text-[12px] transition-colors duration-150",
                    filter === f.id ? "border-foreground bg-foreground text-background" : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  {f.label}
                  <span className="ml-1.5 tabular-nums opacity-70">
                    {f.id === "all" ? all.length : all.filter((s) => (f.id === "on") === s.keys.length > 0).length}
                  </span>
                </button>
              ))}
            </div>
            <label className="relative ml-auto w-60">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-subtle" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search services" className="h-8 pl-8 text-[13px]" aria-label="Search services" />
            </label>
          </div>

          <div className="divide-y rounded-lg border">
            {!services && <p className="p-4 text-[13px] text-subtle">Reading the connections…</p>}
            {services && shown.length === 0 && <p className="p-4 text-[13px] text-subtle">No service matches. Try All, or clear the search.</p>}
            {shown.map((s) => (
              <ServiceRow key={s.id} service={s} onOpen={() => setOpen(s.id)} onChange={changed} />
            ))}
          </div>
        </div>
      </div>

      <Dialog open={!!current} onOpenChange={(o) => !o && setOpen(null)}>
        {current && <Manage service={current} onChange={changed} />}
      </Dialog>
    </Page>
  )
}

function SideItem({ active, onClick, label, n }: { active: boolean; onClick: () => void; label: string; n: number }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "true" : undefined}
      className={cn(
        "flex h-8 items-center justify-between rounded-md px-2.5 text-left text-[13px] transition-colors duration-150",
        active ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
      )}
    >
      {label}
      <span className="text-[12px] text-subtle tabular-nums">{n}</span>
    </button>
  )
}

/** One service: logo, name, status badge and one line; keys underneath when connected; the switch and one button on the right. */
function ServiceRow({ service, onOpen, onChange }: { service: Service; onOpen: () => void; onChange: () => Promise<void> }) {
  const on = service.keys.length > 0
  async function toggle(next: boolean) {
    try {
      await setPaused(service.id, !next)
      toast.success(next ? `${service.label} is on again` : `${service.label} is paused; the next service takes over`)
      await onChange()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }
  return (
    <div className="flex items-center gap-4 px-4 py-3.5">
      <ServiceLogo id={service.id} label={service.label} dim={!on || service.paused} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-medium">{service.label}</span>
          {on && !service.paused && <span className="rounded-full bg-free/12 px-2 text-[11px] leading-[18px] font-medium text-free">Connected</span>}
          {on && service.paused && <span className="rounded-full bg-gold/15 px-2 text-[11px] leading-[18px] font-medium text-gold-ink">Paused</span>}
          <span className={cn("text-[12px]", service.paid ? "text-paid" : "text-subtle")}>{service.paid ? "Paid" : "Free"}</span>
        </div>
        <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground" title={service.for}>
          {service.for}
        </p>
        {on && (
          <p className="mt-1 text-[12px] text-subtle tabular-nums">
            {service.keys.map((k) => `Key ${k.n} ${Object.values(k.masked).slice(-1)[0]}`).join("  ·  ")}
          </p>
        )}
      </div>
      {on && service.pausable && (
        <Switch
          checked={!service.paused}
          onCheckedChange={toggle}
          aria-label={`${service.label} on`}
          title={service.paused ? "Paused: the studio skips it" : "On: the studio uses it"}
          className="data-checked:bg-free"
        />
      )}
      <Button size="sm" variant={on ? "ghost" : "outline"} className="w-24" onClick={onOpen}>
        {on ? "Manage" : "Connect"}
      </Button>
    </div>
  )
}

/** The dialog for one service: its keys (use first, remove) and adding one. */
function Manage({ service, onChange }: { service: Service; onChange: () => Promise<void> }) {
  const [adding, setAdding] = useState(service.keys.length === 0)
  const [removing, setRemoving] = useState<Key | null>(null)
  const several = service.keys.length > 1 && !service.single
  const canAdd = !(service.single && service.keys.length > 0)

  return (
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <div className="flex items-center gap-3">
          <ServiceLogo id={service.id} label={service.label} dim={service.keys.length === 0} />
          <div>
            <DialogTitle>{service.label}</DialogTitle>
            <DialogDescription className="mt-0.5">{service.for}</DialogDescription>
          </div>
        </div>
      </DialogHeader>

      <p className="text-[12.5px] text-muted-foreground">
        {service.limit}{" "}
        <a href={service.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-link hover:underline">
          Get a key <ExternalLink className="size-3" />
        </a>
      </p>

      {service.keys.length > 0 && (
        <div className="divide-y rounded-md border">
          {service.keys.map((k) => (
            <div key={k.slot} className="flex h-11 items-center gap-3 px-3 text-[13px]">
              <span className="font-medium">Key {k.n}</span>
              <span className="text-subtle tabular-nums">{Object.values(k.masked).slice(-1)[0]}</span>
              {several && k.active && <span className="text-[12px] text-free">Used first</span>}
              <span className="ml-auto flex items-center gap-1">
                {several && !k.active && (
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={async () => {
                      await api.useKey(service.id, k.slot)
                      await onChange()
                    }}
                  >
                    Use first
                  </Button>
                )}
                {removing?.slot === k.slot ? (
                  <>
                    <Button
                      size="xs"
                      variant="destructive"
                      onClick={async () => {
                        await api.removeKey(service.id, k.slot)
                        setRemoving(null)
                        toast.success(`${service.label} key ${k.n} removed`)
                        await onChange()
                      }}
                    >
                      Remove
                    </Button>
                    <Button size="xs" variant="ghost" onClick={() => setRemoving(null)}>
                      Keep
                    </Button>
                  </>
                ) : (
                  <Button size="icon-xs" variant="ghost" aria-label={`Remove key ${k.n}`} onClick={() => setRemoving(k)}>
                    <X />
                  </Button>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {adding ? (
        <AddKey service={service} onDone={async () => (setAdding(false), await onChange())} onCancel={service.keys.length ? () => setAdding(false) : undefined} />
      ) : (
        canAdd && (
          <Button variant="outline" className="self-start" onClick={() => setAdding(true)}>
            <Plus /> Add {service.keys.length ? "another key" : "a key"}
          </Button>
        )
      )}
      {several && <p className="text-[12px] text-subtle">Keys from different accounts each have their own free limit; when one runs out, the next is used.</p>}
    </DialogContent>
  )
}

function AddKey({ service, onDone, onCancel }: { service: KeyService; onDone: () => Promise<void>; onCancel?: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const filled = service.fields.every((f) => values[f.name]?.trim())

  async function save() {
    setSaving(true)
    setProblem(null)
    try {
      await api.addKey(service.id, values)
      toast.success(`${service.label} connected`)
      setValues({})
      await onDone()
    } catch (err) {
      setProblem((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      {service.fields.map((f, i) => (
        <label key={f.name} className="block">
          <span className="mb-1 block text-[12.5px] text-secondary-foreground">{f.label}</span>
          <Input
            autoFocus={i === 0}
            type={/ID|USERNAME|REGION/.test(f.name) ? "text" : "password"}
            autoComplete="off"
            spellCheck={false}
            value={values[f.name] ?? ""}
            onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
            onKeyDown={(e) => e.key === "Enter" && filled && !saving && save()}
          />
        </label>
      ))}
      {problem && <p className="text-[12.5px] text-destructive">{problem}</p>}
      <div className="flex gap-2">
        <Button onClick={save} disabled={!filled || saving}>
          {saving ? "Checking…" : service.keys.length ? "Add key" : "Connect"}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </div>
  )
}
