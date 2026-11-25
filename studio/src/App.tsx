import { Check, ChevronDown, Loader2, Lock, RefreshCw } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { Toaster, toast } from "sonner"

import { api, type Job, type State } from "@/api"
import { RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { next, steps, usd, type Step, type StepId } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { FilmView } from "@/views/FilmView"
import { ReferencesView } from "@/views/ReferencesView"
import { ScenesView } from "@/views/ScenesView"
import { StoryView } from "@/views/StoryView"

export type Studio = {
  state: State
  refresh: () => Promise<void>
  /** Start a pipeline job; the shell follows its log and refreshes when it ends. */
  track: (start: Promise<Job>) => Promise<void>
  busy: boolean
  job: Job | null
  /** Open a step, and optionally one scene in it. */
  go: (view: StepId, scene?: string) => void
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

export default function App() {
  const [state, setState] = useState<State | null>(null)
  const [view, setView] = useState<StepId>(() => (read("view") as StepId) || "scenes")
  const [scene, setScene] = useState(() => read("scene") ?? "")
  const [job, setJob] = useState<Job | null>(null)
  const poll = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      setState(await api.state())
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
          if (current.status === "done") toast.success(`${current.kind}: done`)
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
      } catch (err) {
        toast.error((err as Error).message)
      }
    },
    [follow],
  )

  const go = useCallback((v: StepId, s?: string) => {
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
  useEffect(() => write("view", view), [view])
  useEffect(() => write("scene", scene), [scene])

  const busy = job?.status === "running"
  const studio: Studio | null = state ? { state, refresh, track, busy, job, go, scene } : null

  return (
    <div className="grid h-screen grid-cols-[240px_minmax(0,1fr)] overflow-hidden">
      <aside className="flex h-screen flex-col border-r bg-card/40 px-3 py-4">
        <div className="mb-5 flex items-center gap-2 px-2">
          <span className="size-4 rounded-[4px] bg-primary" />
          <span className="text-[13px] font-semibold tracking-tight">{state?.storyboard?.title ?? "10x video gen"}</span>
        </div>
        <nav className="flex flex-col gap-0.5">
          {state &&
            steps(state).map((s, i) => (
              <StepLink key={s.id} step={s} n={i + 1} active={view === s.id} onClick={() => s.state !== "locked" && setView(s.id)} />
            ))}
        </nav>
        {studio && <NextStep studio={studio} onGo={setView} />}
        {state && (
          <div className="mt-3 px-2 text-[12px] text-subtle">
            <span className="text-muted-foreground">{usd(state.spent)}</span> spent at WaveSpeed · {state.calls} calls
          </div>
        )}
      </aside>
      <main className="relative min-w-0 overflow-y-auto">
        {!studio && <div className="p-10 text-muted-foreground">Loading the project…</div>}
        {studio && view === "story" && <StoryView studio={studio} />}
        {studio && view === "references" && <ReferencesView studio={studio} />}
        {studio && view === "scenes" && <ScenesView studio={studio} onScene={setScene} />}
        {studio && view === "film" && <FilmView studio={studio} />}
      </main>
      {job && <JobBar job={job} onClose={() => job.status !== "running" && setJob(null)} />}
      <Toaster theme="system" position="bottom-right" />
    </div>
  )
}

function StepLink({ step, n, active, onClick }: { step: Step; n: number; active: boolean; onClick: () => void }) {
  const locked = step.state === "locked"
  return (
    <button
      onClick={onClick}
      disabled={locked}
      className={cn(
        "group flex items-start gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:hover:bg-transparent",
        active && "bg-muted",
      )}
    >
      <span
        className={cn(
          "mt-0.5 grid size-[18px] shrink-0 place-items-center rounded-full border text-[10.5px] font-semibold tabular-nums",
          step.state === "done" && "border-free/40 bg-free/12 text-free",
          step.state === "stale" && "border-warn/40 bg-warn/12 text-warn",
          step.state === "todo" && "border-primary/50 text-primary",
          locked && "text-subtle",
        )}
      >
        {step.state === "done" ? <Check className="size-3" strokeWidth={3} /> : step.state === "stale" ? <RefreshCw className="size-2.5" strokeWidth={3} /> : locked ? <Lock className="size-2.5" /> : n}
      </span>
      <span className="min-w-0">
        <span className={cn("block text-[13px] font-medium", locked ? "text-subtle" : active ? "text-foreground" : "text-secondary-foreground")}>{step.label}</span>
        <span className={cn("block truncate text-[12px]", step.state === "stale" ? "text-warn" : "text-subtle")}>{step.note}</span>
      </span>
    </button>
  )
}

function NextStep({ studio, onGo }: { studio: Studio; onGo: (v: StepId) => void }) {
  const { state, track, busy, job } = studio
  const n = next(state)
  return (
    <div className="mt-auto rounded-lg border bg-background p-3">
      <div className="mb-1 text-[11px] font-medium tracking-wide text-primary uppercase">Next step</div>
      {busy ? (
        <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin text-primary" />
          <span className="truncate">{job?.kind} is running…</span>
        </div>
      ) : (
        <>
          <div className="text-[13px] leading-snug font-medium">{n.title}</div>
          <p className="mt-1 mb-3 text-[12px] leading-snug text-muted-foreground">{n.detail}</p>
          {n.run ? (
            <RunButton size="sm" className="w-full" cost={n.cost} spent={state.spent} onRun={() => (onGo(n.step), track(n.run!()))}>
              {n.label}
            </RunButton>
          ) : (
            <Button size="sm" variant="secondary" className="w-full" onClick={() => onGo(n.step)}>
              {n.label}
            </Button>
          )}
        </>
      )}
    </div>
  )
}

function JobBar({ job, onClose }: { job: Job; onClose: () => void }) {
  const [open, setOpen] = useState(false)
  const last = job.log[job.log.length - 1] ?? "starting…"
  return (
    <div className="fixed right-4 bottom-4 left-[256px] z-20">
      <div className="mx-auto max-w-3xl rounded-xl border bg-popover/95 shadow-2xl backdrop-blur">
        <div className="flex items-center gap-3 px-4 py-2.5">
          {job.status === "running" ? (
            <Loader2 className="size-4 animate-spin text-primary" />
          ) : (
            <span className={cn("size-2 rounded-full", job.status === "done" ? "bg-free" : "bg-destructive")} />
          )}
          <span className="font-medium">{job.kind}</span>
          <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground">{last}</span>
          <Button variant="ghost" size="xs" onClick={() => setOpen(!open)}>
            Log <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
          </Button>
          {job.status !== "running" && (
            <Button variant="ghost" size="xs" onClick={onClose}>
              Dismiss
            </Button>
          )}
        </div>
        {open && (
          <pre className="max-h-64 overflow-auto border-t px-4 py-3 font-mono text-[12px] leading-5 text-muted-foreground">{job.log.join("\n") || "…"}</pre>
        )}
      </div>
    </div>
  )
}
