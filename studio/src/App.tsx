import { BookOpen, Clapperboard, Film, Images, Loader2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { Toaster, toast } from "sonner"

import { api, type Job, type State } from "@/api"
import { cn } from "@/lib/utils"
import { FilmView } from "@/views/FilmView"
import { ReferencesView } from "@/views/ReferencesView"
import { ScenesView } from "@/views/ScenesView"
import { StoryView } from "@/views/StoryView"

const VIEWS = [
  { id: "story", label: "Story", icon: BookOpen },
  { id: "references", label: "References", icon: Images },
  { id: "scenes", label: "Scenes", icon: Clapperboard },
  { id: "film", label: "Film", icon: Film },
] as const
type ViewId = (typeof VIEWS)[number]["id"]

export type Studio = {
  state: State
  refresh: () => Promise<void>
  /** Start a pipeline job; the shell follows its log and refreshes when it ends. */
  track: (start: Promise<Job>) => Promise<void>
  busy: boolean
}

export default function App() {
  const [state, setState] = useState<State | null>(null)
  const [view, setView] = useState<ViewId>(() => (localStorage.getItem("view") as ViewId) || "scenes")
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
  useEffect(() => localStorage.setItem("view", view), [view])

  const busy = job?.status === "running"
  const studio: Studio | null = state ? { state, refresh, track, busy } : null

  return (
    <div className="grid min-h-screen grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)]">
      <aside className="sticky top-0 z-10 flex flex-wrap items-center gap-1 border-b bg-background/90 px-3 py-2 backdrop-blur md:h-screen md:flex-col md:flex-nowrap md:items-stretch md:border-r md:border-b-0 md:px-3 md:py-5">
        <div className="mr-3 px-2 text-[13px] font-semibold tracking-tight md:mb-4 md:mr-0">10x video gen</div>
        {VIEWS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setView(id)}
            className={cn(
              "flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              view === id && "bg-muted text-foreground",
            )}
          >
            <Icon className="size-4 opacity-80" />
            {label}
          </button>
        ))}
        {state && (
          <div className="ml-auto text-[12px] text-subtle md:mt-auto md:ml-0 md:px-2">
            {state.calls} calls · ${state.spent.toFixed(3)} spent
          </div>
        )}
      </aside>
      <main className="min-w-0 pb-28">
        {!studio && <div className="p-10 text-muted-foreground">Loading the project…</div>}
        {studio && view === "story" && <StoryView studio={studio} />}
        {studio && view === "references" && <ReferencesView studio={studio} />}
        {studio && view === "scenes" && <ScenesView studio={studio} />}
        {studio && view === "film" && <FilmView studio={studio} />}
      </main>
      {job && <JobBar job={job} onClose={() => job.status !== "running" && setJob(null)} />}
      <Toaster theme="system" position="bottom-right" />
    </div>
  )
}

function JobBar({ job, onClose }: { job: Job; onClose: () => void }) {
  const [open, setOpen] = useState(false)
  const last = job.log[job.log.length - 1] ?? "starting…"
  return (
    <div className="fixed inset-x-3 bottom-3 z-20 md:left-[232px]">
      <div className="mx-auto max-w-3xl rounded-xl border bg-popover/95 shadow-2xl backdrop-blur">
        <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left">
          {job.status === "running" ? (
            <Loader2 className="size-4 animate-spin text-primary" />
          ) : (
            <span className={cn("size-2 rounded-full", job.status === "done" ? "bg-free" : "bg-destructive")} />
          )}
          <span className="font-medium">{job.kind}</span>
          <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground">{last}</span>
          {job.status !== "running" && (
            <span onClick={(e) => (e.stopPropagation(), onClose())} className="text-[12px] text-subtle hover:text-foreground">
              Dismiss
            </span>
          )}
        </button>
        {open && (
          <pre className="max-h-64 overflow-auto border-t px-4 py-3 font-mono text-[12px] leading-5 text-muted-foreground">
            {job.log.join("\n") || "…"}
          </pre>
        )}
      </div>
    </div>
  )
}
