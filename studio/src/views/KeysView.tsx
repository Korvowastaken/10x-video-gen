import { ExternalLink, Plus, X } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"

import { api, type KeyService } from "@/api"
import type { Studio } from "@/App"
import { PurposeRows } from "@/components/providers-panel"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { Page, Section } from "@/views/parts"

type Key = KeyService["keys"][number]

/** How the connections are grouped on the page, by the work they do. Unknown services land in the last group. */
const GROUPS: { title: string; ids: string[] }[] = [
  { title: "Writing and voices", ids: ["anthropic", "azure", "gemini"] },
  { title: "Pictures, clips and music", ids: ["cloudflare", "wavespeed", "kaggle"] },
  { title: "Other free writers (optional)", ids: ["groq", "cerebras", "openrouter"] },
]

export function KeysView({ studio }: { studio: Studio }) {
  const [services, setServices] = useState<KeyService[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const load = useCallback(async () => {
    try {
      setServices(await api.keys())
    } catch (err) {
      toast.error(`Could not read the keys: ${(err as Error).message}`)
    }
  }, [])
  useEffect(() => {
    load()
  }, [load])
  const changed = async () => {
    await load()
    await studio.refresh()
  }
  const known = new Set(GROUPS.flatMap((g) => g.ids))
  const groups = GROUPS.map((g, i) => ({
    title: g.title,
    items: (services ?? []).filter((s) => g.ids.includes(s.id) || (i === GROUPS.length - 1 && !known.has(s.id))),
  })).filter((g) => g.items.length)
  const connected = services?.filter((s) => s.keys.length).length ?? 0
  const current = services?.find((s) => s.id === open) ?? null

  return (
    <Page className="max-w-6xl">
      <header className="mb-2 border-b pb-5">
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em]">Connections</h1>
        <p className="mt-1 max-w-2xl text-muted-foreground">
          {services ? `${connected} of ${services.length} services connected. ` : ""}
          Keys stay in the .env file on this computer. When a free limit runs out, the next key for the same service takes over by itself.
        </p>
      </header>

      <Section title="What makes what">
        <PurposeRows studio={studio} />
      </Section>

      {!services && <p className="mt-8 text-[13px] text-subtle">Reading the connections…</p>}
      {groups.map((g) => (
        <Section key={g.title} title={g.title} className="mt-10">
          <div className="grid grid-cols-3 gap-3">
            {g.items.map((s) => (
              <Connector key={s.id} service={s} onOpen={() => setOpen(s.id)} />
            ))}
          </div>
        </Section>
      ))}

      <Dialog open={!!current} onOpenChange={(o) => !o && setOpen(null)}>
        {current && <Manage service={current} onChange={changed} />}
      </Dialog>
    </Page>
  )
}

/** A service's mark: its initials on a tile, since the studio ships no third-party logos. */
function Mark({ label, on }: { label: string; on: boolean }) {
  const letters = label.split(/\s+/).map((w) => w[0]).join("").slice(0, 2)
  return (
    <span className={cn("grid size-9 shrink-0 place-items-center rounded-md text-[13px] font-semibold", on ? "bg-foreground text-background" : "border bg-muted text-subtle")}>
      {letters}
    </span>
  )
}

function Connector({ service, onOpen }: { service: KeyService; onOpen: () => void }) {
  const on = service.keys.length > 0
  return (
    <div className="flex flex-col rounded-lg border p-4 transition-colors duration-150 hover:border-thread">
      <div className="flex items-start gap-3">
        <Mark label={service.label} on={on} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[14px] font-medium">{service.label}</span>
            <span className={cn("text-[12px]", service.paid ? "text-paid" : "text-free")}>{service.paid ? "Paid" : "Free"}</span>
          </div>
          <p className="mt-1 line-clamp-2 text-[12.5px] leading-snug text-muted-foreground" title={service.for}>
            {service.for}
          </p>
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between gap-2 pt-1">
        <span className={cn("inline-flex items-center gap-1.5 text-[12px]", on ? "text-free" : "text-subtle")}>
          <span className={cn("size-1.5 rounded-full", on ? "bg-free" : "border border-thread")} />
          {on ? `Connected${service.keys.length > 1 ? ` · ${service.keys.length} keys` : ""}` : "Not connected"}
        </span>
        <Button size="sm" variant={on ? "ghost" : "outline"} onClick={onOpen}>
          {on ? "Manage" : "Connect"}
        </Button>
      </div>
    </div>
  )
}

/** The dialog for one service: its keys (use first, remove) and adding one. */
function Manage({ service, onChange }: { service: KeyService; onChange: () => Promise<void> }) {
  const [adding, setAdding] = useState(service.keys.length === 0)
  const [removing, setRemoving] = useState<Key | null>(null)
  const several = service.keys.length > 1 && !service.single
  const canAdd = !(service.single && service.keys.length > 0)

  return (
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <div className="flex items-center gap-3">
          <Mark label={service.label} on={service.keys.length > 0} />
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
      {service.keys.length > 1 && !service.single && (
        <p className="text-[12px] text-subtle">Keys from different accounts each have their own free limit; when one runs out, the next is used.</p>
      )}
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
