import { Check, ChevronDown, ChevronsUpDown, KeyRound, Monitor, Moon, Pencil, Plus, Sun } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { Toaster, toast } from "sonner"

import { api, type Flow, type Job, type State, type StoryItem } from "@/api"
import { JobBar } from "@/components/job-bar"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { LimitsContext } from "@/lib/limits"
import { back, steps, usd, VIEW_OF, type Step, type StepId } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { FilmView } from "@/views/FilmView"
import { KeysView } from "@/views/KeysView"
import { ScriptView } from "@/views/ScriptView"
import { SketchView } from "@/views/SketchView"
import { ReferencesView } from "@/views/ReferencesView"
import { ScenesView } from "@/views/ScenesView"
import { StoryView } from "@/views/StoryView"

export type Studio = {
  state: State
  /** The six steps: what is approved, stale or locked, prices and the budget (pipeline/flow.py). */
  flow: Flow
  refresh: () => Promise<void>
  /** Start a pipeline job; the shell follows its log and refreshes when it ends. Gives the started job. */
  track: (start: Promise<Job>) => Promise<Job | null>
  /** Start a job and wait for it to end: the finished job (with its `result`), or null if it never started. */
  finish: (start: Promise<Job>) => Promise<Job | null>
  busy: boolean
  job: Job | null
  /** Open a step, and optionally one scene in it. */
  go: (view: View, scene?: string) => void
  scene: string
}

const read = (key: string) => {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
const write = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private window: the choice is just not remembered */
  }
}

/** The six steps, plus the Keys page beside them. */
export type View = StepId | "keys"

export default function App() {
  const [state, setState] = useState<State | null>(null)
  const [flow, setFlow] = useState<Flow | null>(null)
  const [view, setView] = useState<View>(() => (read("view") as View) || "scenes")
  const [scene, setScene] = useState(() => read("scene") ?? "")
  const [job, setJob] = useState<Job | null>(null)
  const poll = useRef<number | null>(null)
  /** Who waits for which job to end (see finish). */
  const waiters = useRef(new Map<string, (job: Job) => void>())
  /** Set once the page has opened on a step it can work in; cleared when another story opens. */
  const landed = useRef(false)

  const refresh = useCallback(async () => {
    try {
      const [s, f] = await Promise.all([api.state(), api.flow()])
      setState(s)
      setFlow(f)
    } catch (err) {
      toast.error(`Could not reach the studio API: ${(err as Error).message}`)
    }
  }, [])

  const follow = useCallback(
    (id: string) => {
      if (poll.current) window.clearInterval(poll.current)
      poll.current = window.setInterval(async () => {
        const current = await api.job(id).catch(() => null)
        if (!current) return
        setJob(current)
        if (current.status !== "running") {
          window.clearInterval(poll.current!)
          poll.current = null
          waiters.current.get(id)?.(current)
          waiters.current.delete(id)
          if (current.status === "done") toast.success(`${current.kind}: done`)
          else if (current.status === "cancelled") toast(`${current.kind}: stopped`, { description: "What finished before the stop is kept." })
          else toast.error(`${current.kind}: ${current.error ?? "failed"}`)
          refresh()
        }
      }, 1200)
    },
    [refresh],
  )

  const track = useCallback(
    async (start: Promise<Job>) => {
      try {
        const started = await start
        setJob(started)
        follow(started.id)
        return started
      } catch (err) {
        toast.error((err as Error).message)
        return null
      }
    },
    [follow],
  )

  const finish = useCallback(
    async (start: Promise<Job>) => {
      const started = await track(start)
      return started && new Promise<Job>((resolve) => waiters.current.set(started.id, resolve))
    },
    [track],
  )

  const go = useCallback((v: View, s?: string) => {
    setView(v)
    if (s) setScene(s)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])
  useEffect(() => {
    const running = state?.jobs.find((j) => j.status === "running")
    if (running && !poll.current) {
      setJob(running)
      follow(running.id)
    }
  }, [state, follow])
  // A used-up free limit comes back at its reset time; look again each minute so the page notices.
  const waiting = Object.values(state?.limits ?? {}).some((l) => l.used_up)
  useEffect(() => {
    if (!waiting) return
    const id = window.setInterval(refresh, 60_000)
    return () => window.clearInterval(id)
  }, [waiting, refresh])
  // Open on the remembered step, unless it is locked (a new story, say): then on the step the film is at.
  useEffect(() => {
    if (!flow || landed.current) return
    landed.current = true
    if (view !== "keys" && steps(flow).find((s) => s.id === view)?.state === "locked") setView(VIEW_OF[flow.current ?? "story"])
  }, [flow, view])
  useEffect(() => write("view", view), [view])
  useEffect(() => write("scene", scene), [scene])

  const busy = job?.status === "running"
  const opened = useCallback(async () => {
    landed.current = false
    setJob(null)
    await refresh()
  }, [refresh])
  const studio: Studio | null = state && flow ? { state, flow, refresh, track, finish, busy, job, go, scene } : null

  return (
    <LimitsContext.Provider value={state?.limits}>
    <div className="grid h-screen grid-cols-[288px_minmax(0,1fr)] overflow-hidden">
      <aside className="relative flex h-screen flex-col border-r bg-card">
        <div className="flex h-[68px] items-center gap-2 border-b pr-10 pl-6">
          <img src="/logo.png" alt="" className="size-7 shrink-0 rounded-[5px]" />
          <StorySwitcher busy={busy} onOpened={opened} />
        </div>
        <nav aria-label="Steps" className="relative">
          {flow &&
            steps(flow).map((s, i) => (
              <StepLink key={s.id} step={s} n={i + 1} active={view === s.id} onClick={() => setView(s.id)} />
            ))}
        </nav>
        {/* the undyed warp under the band, so locked steps still show the cloth's edge */}
        <span aria-hidden className="pointer-events-none absolute inset-y-0 right-0 w-3.5 border-x border-thread" />
        {state && <Account state={state} flow={flow} active={view === "keys"} onKeys={() => setView("keys")} />}
      </aside>
      <main className="relative min-w-0 overflow-y-auto">
        {!studio && <div className="p-10 text-muted-foreground">Loading the project…</div>}
        {studio && view === "story" && <StoryView studio={studio} />}
        {studio && view === "script" && <ScriptView studio={studio} />}
        {studio && view === "sketch" && <SketchView studio={studio} />}
        {studio && view === "references" && <ReferencesView studio={studio} />}
        {studio && view === "scenes" && <ScenesView studio={studio} onScene={setScene} />}
        {studio && view === "film" && <FilmView studio={studio} />}
        {studio && view === "keys" && <KeysView studio={studio} />}
      </main>
      {job && <JobBar job={job} onClose={() => job.status !== "running" && setJob(null)} />}
      <Toaster theme="system" position="bottom-right" />
    </div>
    </LimitsContext.Provider>
  )
}

/** Which story is open, the others to switch to, and a new one. Each story is its own film. */
function StorySwitcher({ busy, onOpened }: { busy: boolean; onOpened: () => Promise<void> }) {
  const [list, setList] = useState<StoryItem[]>([])
  const [naming, setNaming] = useState<"new" | "rename" | null>(null)
  const load = useCallback(() => api.stories().then(setList).catch(() => {}), [])
  useEffect(() => void load(), [load])
  const current = list.find((s) => s.current)

  async function open(story: StoryItem) {
    if (story.current) return
    try {
      setList(await api.openStory(story.id))
      await onOpened()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function name(text: string) {
    try {
      if (naming === "new") {
        setList(await api.newStory(text))
        await onOpened()
      } else if (current) setList(await api.renameStory(current.id, text))
      setNaming(null)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <>
      <DropdownMenu onOpenChange={(open) => open && load()}>
        <DropdownMenuTrigger
          aria-label="Switch story"
          title={current?.name}
          className="-mx-1.5 flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors duration-150 hover:bg-secondary data-popup-open:bg-secondary"
        >
          <span className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-tight">{current?.name ?? "Story"}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-subtle" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" sideOffset={8} className="w-64 p-1.5">
          <DropdownMenuGroup>
            <DropdownMenuLabel className="px-2 pt-1 pb-1.5 text-[12px] font-normal text-subtle">
              {busy ? "Switch stories once the running job ends" : "Stories"}
            </DropdownMenuLabel>
            {list.map((s) => (
              <DropdownMenuItem key={s.id} disabled={busy && !s.current} onClick={() => open(s)} className="gap-2.5 px-2 py-1.5">
                <Check className={cn("size-3.5 text-free", !s.current && "invisible")} strokeWidth={2.5} />
                <span className="min-w-0 flex-1">
                  <span className={cn("block truncate text-[13.5px]", s.current && "font-medium")}>{s.name}</span>
                  <span className="block text-[11.5px] text-subtle">{s.drafted ? "Script drafted" : s.written ? "Story written" : "Not started"}</span>
                </span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator className="my-1.5" />
          <DropdownMenuItem disabled={busy} onClick={() => setNaming("new")} className="gap-2.5 px-2 py-1.5 text-[13.5px]">
            <Plus className="size-3.5 text-subtle" /> New story
          </DropdownMenuItem>
          {current && (
            <DropdownMenuItem onClick={() => setNaming("rename")} className="gap-2.5 px-2 py-1.5 text-[13.5px]">
              <Pencil className="size-3.5 text-subtle" /> Rename this story
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <StoryName
        open={naming !== null}
        rename={naming === "rename"}
        initial={naming === "rename" ? (current?.name ?? "") : ""}
        onClose={() => setNaming(null)}
        onSave={name}
      />
    </>
  )
}

/** Name a new story, or rename the open one. */
function StoryName({ open, rename, initial, onClose, onSave }: { open: boolean; rename: boolean; initial: string; onClose: () => void; onSave: (name: string) => Promise<void> }) {
  const [text, setText] = useState(initial)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (open) setText(initial)
  }, [open, initial])

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    await onSave(text.trim())
    setSaving(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <form onSubmit={save} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{rename ? "Rename this story" : "New story"}</DialogTitle>
            <DialogDescription>
              {rename ? "Only its name in the list changes." : "A fresh film with its own story, script and pictures. Your other stories stay as they are."}
            </DialogDescription>
          </DialogHeader>
          <Input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="The market walk" aria-label="Story name" />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || (rename && !text.trim())}>
              {rename ? "Save name" : "Start story"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** The band segment and number colour for each step state: woven green when approved, gold where the maker is, red when it changed. */
const WEAVE: Record<Step["state"], string> = { done: "weave-done", todo: "weave-current", stale: "weave-stale", locked: "weave-locked" }

function StepLink({ step, n, active, onClick }: { step: Step; n: number; active: boolean; onClick: () => void }) {
  const locked = step.state === "locked"
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      title={locked ? step.note : undefined}
      className={cn(
        "relative z-10 flex h-[60px] w-full items-center gap-3 border-b pr-10 pl-6 text-left transition-colors duration-150 hover:bg-secondary",
        active && "bg-background hover:bg-background",
      )}
    >
      <span
        className={cn(
          "grid size-6 shrink-0 place-items-center rounded-full border text-[12px] font-semibold tabular-nums",
          step.state === "done" && "border-free bg-free text-white",
          step.state === "todo" && "border-gold bg-gold text-foreground",
          step.state === "stale" && "border-warn bg-warn text-white",
          locked && "border-thread text-subtle",
        )}
      >
        {n}
      </span>
      <span className="min-w-0">
        <span className={cn("block text-[14px] font-medium", locked ? "text-subtle" : "text-foreground", active && "font-semibold")}>{step.label}</span>
        <span className={cn("block truncate text-[12px]", locked ? "text-subtle" : step.state === "stale" ? "text-warn" : step.state === "done" ? "text-free" : "text-muted-foreground")}>
          {locked ? `Opens after ${step.note.replace(/^After /, "")}` : step.note}
        </span>
      </span>
      <span aria-hidden className={cn("absolute inset-y-0 right-0 w-3.5", WEAVE[step.state])} />
    </button>
  )
}

/** Free limits today (and when a used-up one comes back), what the film has spent of its budget, and the keys. */
function Account({ state, flow, active, onKeys }: { state: State; flow: Flow | null; active: boolean; onKeys: () => void }) {
  const [open, setOpen] = useState(() => read("account-open") === "1")
  useEffect(() => write("account-open", open ? "1" : "0"), [open])
  const limits = Object.entries(state.limits ?? {})
  const out = limits.filter(([, l]) => l.used_up)
  const budget = flow?.budget?.budget_usd ?? 0
  const share = budget ? Math.min(1, state.spent / budget) : 0
  return (
    <div className="relative z-10 mt-auto border-t bg-card px-6 pt-3 pb-4 text-[12px]">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="-mx-2 flex w-[calc(100%+16px)] items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-150 hover:bg-secondary"
      >
        <span className={cn("size-1.5 shrink-0 rounded-full", out.length ? "bg-warn" : "bg-free")} />
        <span className={cn("min-w-0 flex-1 truncate", out.length && "text-warn")}>
          {out.length ? `${out.length} free limit${out.length > 1 ? "s" : ""} used up` : "Free limits available"}
        </span>
        <span className="shrink-0 text-muted-foreground tabular-nums">{usd(state.spent)}</span>
        <ChevronDown className={cn("size-3.5 shrink-0 text-subtle transition-transform duration-150", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mt-2 mb-1">
          {limits.map(([id, l]) => (
            <div key={id} className="flex justify-between gap-3 py-0.5" title={l.used_up ? `Back ${back(l).text}` : undefined}>
              <span className="truncate">{l.label}</span>
              <span className={cn("shrink-0 tabular-nums", l.used_up ? "text-warn" : "text-muted-foreground")}>
                {l.used_up ? `back ${back(l).time}` : l.left != null ? `~${l.left} left` : "Free"}
              </span>
            </div>
          ))}
          <div className="mt-3 mb-1.5 h-1 bg-border" title={`${state.calls} paid calls so far`}>
            <div className="h-1 bg-free" style={{ width: `${Math.max(share * 100, state.spent ? 2 : 0)}%` }} />
          </div>
          <div className="flex justify-between tabular-nums">
            <span>{usd(state.spent)} spent</span>
            {budget > 0 && <span className="text-muted-foreground">of {usd(budget)} film budget</span>}
          </div>
        </div>
      )}
      <div className="mt-2 flex items-center justify-between">
        <button
          onClick={onKeys}
          aria-current={active ? "page" : undefined}
          className={cn("inline-flex items-center gap-1.5 text-link hover:underline", active && "font-semibold")}
        >
          <KeyRound className="size-3.5" />
          Connections
        </button>
        <ThemeSwitch />
      </div>
    </div>
  )
}

type Theme = "system" | "light" | "dark"
const THEMES: { id: Theme; label: string; Icon: typeof Sun }[] = [
  { id: "system", label: "Follow the computer", Icon: Monitor },
  { id: "light", label: "Light", Icon: Sun },
  { id: "dark", label: "Dark", Icon: Moon },
]

/** Light, dark, or whatever the computer uses. Remembered in this browser. */
function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(() => (read("theme") as Theme) || "system")
  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme
    else document.documentElement.dataset.theme = theme
    write("theme", theme)
  }, [theme])
  return (
    <div role="radiogroup" aria-label="Colours" className="flex rounded-md border p-0.5">
      {THEMES.map(({ id, label, Icon }) => (
        <button
          key={id}
          role="radio"
          aria-checked={theme === id}
          title={label}
          onClick={() => setTheme(id)}
          className={cn("grid size-6 place-items-center rounded-[4px] text-subtle transition-colors duration-150 hover:text-foreground", theme === id && "bg-secondary text-foreground")}
        >
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  )
}
