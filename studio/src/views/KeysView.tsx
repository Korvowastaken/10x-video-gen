import { ExternalLink, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"

import { api, type KeyService, type State } from "@/api"
import type { Studio } from "@/App"
import { CostTag } from "@/components/run-button"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { back, FREE } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { Page, StatusDot } from "@/views/parts"

export function KeysView({ studio }: { studio: Studio }) {
  const [services, setServices] = useState<KeyService[] | null>(null)
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

  return (
    <Page className="max-w-5xl">
      <header className="mb-7">
        <h1 className="text-2xl font-semibold tracking-tight">Keys</h1>
        <p className="mt-1 max-w-2xl text-muted-foreground">
          Saved in the .env file on this computer and only ever shown by their last four characters. Free limits belong to the account behind a key,
          so add a second key from another account and the studio switches to it by itself when the first one runs out.
        </p>
      </header>
      {!services && <p className="text-muted-foreground">Reading the keys…</p>}
      <div className="divide-y border-y">
        {services?.map((s) => (
          <Service key={s.id} service={s} limits={studio.state.limits} onChange={changed} />
        ))}
      </div>
    </Page>
  )
}

function Service({ service, limits, onChange }: { service: KeyService; limits: State["limits"]; onChange: () => Promise<void> }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [removing, setRemoving] = useState<KeyService["keys"][number] | null>(null)
  const [adding, setAdding] = useState(service.keys.length === 0)
  const filled = service.fields.every((f) => values[f.name]?.trim())

  async function save() {
    setSaving(true)
    setProblem(null)
    try {
      await api.addKey(service.id, values)
      toast.success(`${service.label} key added`)
      setValues({})
      setAdding(false)
      await onChange()
    } catch (err) {
      setProblem((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="grid grid-cols-[280px_minmax(0,1fr)] gap-10 py-6">
      <div>
        <div className="flex items-center gap-2">
          <span className="font-medium">{service.label}</span>
          {service.paid ? <span className="rounded-[4px] bg-paid/15 px-1.5 text-[11px] font-medium text-paid">Paid</span> : <CostTag cost={FREE()} />}
        </div>
        <p className="mt-1 text-[12.5px] text-muted-foreground">{service.for}</p>
        <p className="mt-2 text-[12px] text-subtle">{service.limit}</p>
        <a href={service.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[12px] text-primary hover:underline">
          Get a key <ExternalLink className="size-3" />
        </a>
      </div>

      <div className="min-w-0">
        {service.keys.length > 0 && (
          <div className="divide-y rounded-lg border">
            {service.keys.map((k) => (
              <div key={k.slot} className="flex items-center gap-4 px-4 py-2.5">
                <span className="w-14 text-[13px] font-medium">Key {k.n}</span>
                <span className="w-44 truncate font-mono text-[12px] text-muted-foreground">
                  {Object.values(k.masked).join(" · ")}
                </span>
                <KeyStatus service={service.id} fingerprint={k.fingerprint} limits={limits} />
                <span className="ml-auto flex items-center gap-1">
                  {service.single || service.keys.length < 2 ? null : k.active ? (
                    <span className="text-[12px] text-primary">In use</span>
                  ) : (
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={async () => {
                        await api.useKey(service.id, k.slot)
                        await onChange()
                      }}
                    >
                      Use this one
                    </Button>
                  )}
                  <Button size="icon-xs" variant="ghost" aria-label={`Remove ${service.label} key ${k.n}`} onClick={() => setRemoving(k)}>
                    <Trash2 />
                  </Button>
                </span>
              </div>
            ))}
          </div>
        )}

        {adding ? (
          <div className={cn("space-y-2", service.keys.length > 0 && "mt-4")}>
            <div className="flex flex-wrap items-end gap-2">
              {service.fields.map((f) => (
                <label key={f.name} className="min-w-48 flex-1">
                  <span className="mb-1 block text-[12px] text-subtle">{f.label}</span>
                  <Input
                    type={/ID|USERNAME/.test(f.name) ? "text" : "password"}
                    autoComplete="off"
                    spellCheck={false}
                    value={values[f.name] ?? ""}
                    onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && filled && !saving && save()}
                    className="font-mono text-[12.5px]"
                  />
                </label>
              ))}
              <Button onClick={save} disabled={!filled || saving}>
                {saving ? "Checking…" : service.keys.length ? "Add key" : "Save key"}
              </Button>
              {service.keys.length > 0 && (
                <Button variant="ghost" onClick={() => (setAdding(false), setValues({}), setProblem(null))}>
                  Cancel
                </Button>
              )}
            </div>
            {problem ? (
              <p className="text-[12.5px] text-destructive">{problem}</p>
            ) : (
              <p className="text-[12px] text-subtle">
                {service.id === "gemini" || service.id === "cloudflare"
                  ? "Checked with the provider before saving, without using any of its limit."
                  : "Saved as given; it is first used on the next run."}
              </p>
            )}
          </div>
        ) : service.single ? null : (
          <Button variant="outline" size="sm" className="mt-3" onClick={() => setAdding(true)}>
            Add another key
          </Button>
        )}
      </div>

      <AlertDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)}>
        <AlertDialogContent className="data-[size=default]:sm:max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>
              Remove {service.label} key {removing?.n}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              It is deleted from .env on this computer. The account itself is not touched, and you can add the key again later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <Button
              variant="destructive"
              onClick={async () => {
                if (removing) await api.removeKey(service.id, removing.slot)
                setRemoving(null)
                await onChange()
              }}
            >
              Remove key
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

/** What is left on this key today, from the same limits the steps use. */
function KeyStatus({ service, fingerprint, limits }: { service: KeyService["id"]; fingerprint: string; limits: State["limits"] }) {
  if (!limits || (service !== "gemini" && service !== "cloudflare")) return null
  if (service === "cloudflare") {
    const k = limits.pictures.keys?.[fingerprint]
    if (!k) return null
    return k.used_up ? (
      <StatusDot status="stale">Used up today, back {back(limits.pictures).time}</StatusDot>
    ) : (
      <StatusDot status="ok">~{k.left} pictures left today</StatusDot>
    )
  }
  const out = (["writing", "voices"] as const).filter((p) => limits[p].keys?.[fingerprint]?.used_up)
  if (!out.length) return <StatusDot status="ok">Available today</StatusDot>
  return (
    <StatusDot status="stale">
      {out.length === 2 ? "Writing and voices" : out[0] === "writing" ? "Writing" : "Voices"} used up, back {back(limits.writing).time}
    </StatusDot>
  )
}
