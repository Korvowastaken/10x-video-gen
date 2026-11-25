import { Check, ChevronDown, Copy, Loader2, Square } from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { api, type Job, type LogEntry } from "@/api"
import { Button } from "@/components/ui/button"
import { usd } from "@/lib/progress"
import { cn } from "@/lib/utils"

/** 74 → "1:14". */
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`

/** A job's log entry; a job from before the log had levels is plain text. */
const entry = (e: LogEntry | string): LogEntry => (typeof e === "string" ? { at: 0, level: "info", text: e } : e)

/** One line of the log in words, for the bar's summary and for copying. */
function words(e: LogEntry) {
  const c = e.call
  if (!c) return e.text
  const parts = [`${c.provider} · ${c.model}`, `${c.stage} ${c.item}`, c.status === "ok" ? "ok" : c.status]
  if (c.seconds != null) parts.push(`${c.seconds.toFixed(1)} s`)
  if (c.usd) parts.push(usd(c.usd))
  if (c.attempt) parts.push(`attempt ${c.attempt}`)
  return parts.join(" · ") + (c.error ? `\n        ${c.error}` : "")
}

/** Seconds since the job started, ticking while it runs. */
function useElapsed(job: Job) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    if (job.status !== "running") return
    const id = window.setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => window.clearInterval(id)
  }, [job.status])
  return Math.max(0, (job.ended ?? now) - job.started)
}

/**
 * The running (or last) job along the bottom: what it is doing, how long it has run, the calls it
 * made and what they cost, and Stop. The log opens above it, one row per line or model call.
 */
export function JobBar({ job, onClose }: { job: Job; onClose: () => void }) {
  const [open, setOpen] = useState(false)
  const [asked, setAsked] = useState(false)
  const log = job.log.map(entry)
  const last = [...log].reverse().find((e) => e.level !== "done") ?? log[log.length - 1]
  const elapsed = useElapsed(job)
  const running = job.status === "running"
  const stopping = running && (job.stopping || asked)
  const t = job.totals

  async function stop() {
    setAsked(true)
    try {
      await api.stopJob(job.id)
    } catch (err) {
      setAsked(false)
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="fixed right-6 bottom-5 left-[312px] z-20">
      <div className="mx-auto max-w-3xl overflow-hidden rounded-lg border bg-popover shadow-[0_8px_24px_-8px_rgb(29_29_27/0.25)]">
        {open && <Log log={log} running={running} />}
        <div className={cn("flex items-center gap-3 px-4 py-2.5", open && "border-t")}>
          {running ? (
            <Loader2 className={cn("size-4 shrink-0 animate-spin", stopping ? "text-warn" : "text-primary")} />
          ) : (
            <span
              className={cn(
                "size-2 shrink-0 rounded-full",
                job.status === "done" && "bg-free",
                job.status === "error" && "bg-destructive",
                job.status === "cancelled" && "bg-warn",
              )}
            />
          )}
          <span className="shrink-0 font-medium">{job.kind}</span>
          <span className={cn("min-w-0 flex-1 truncate font-mono text-[12px]", stopping ? "text-warn" : "text-muted-foreground")}>
            {stopping ? "Stopping once what is under way finishes…" : last ? words(last).split("\n")[0] : "starting…"}
          </span>
          <span className="shrink-0 text-[12px] text-subtle tabular-nums" title={t ? `${t.calls} model calls, ${t.failed} failed` : undefined}>
            {t && t.calls > 0 && (
              <>
                {t.calls} call{t.calls === 1 ? "" : "s"}
                {t.failed > 0 && <span className="text-destructive"> · {t.failed} failed</span>}
                {t.usd > 0 && ` · ${usd(t.usd)}`}
                {" · "}
              </>
            )}
            {clock(elapsed)}
          </span>
          <Button variant="ghost" size="xs" onClick={() => setOpen(!open)} aria-expanded={open}>
            Log <ChevronDown className={cn("transition-transform duration-150", !open && "rotate-180")} />
          </Button>
          {running ? (
            <Button variant="outline" size="xs" disabled={stopping} onClick={stop} title="Stops once what is under way finishes. Everything made so far is kept.">
              <Square className="size-3 fill-current" /> {stopping ? "Stopping" : "Stop"}
            </Button>
          ) : (
            <Button variant="ghost" size="xs" onClick={onClose}>
              Dismiss
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

const TONE: Record<LogEntry["level"], string> = {
  info: "text-muted-foreground",
  call: "text-foreground",
  warn: "text-warn",
  error: "text-destructive",
  done: "text-free",
}

function Log({ log, running }: { log: LogEntry[]; running: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const pinned = useRef(true) // follow new lines while the reader is at the bottom
  const [copied, setCopied] = useState(false)
  useLayoutEffect(() => {
    const el = box.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [log.length])

  async function copy() {
    try {
      await navigator.clipboard.writeText(log.map((e) => `${clock(e.at)}  ${words(e)}`).join("\n"))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error("Could not copy the log")
    }
  }

  return (
    <div className="relative">
      <Button variant="ghost" size="xs" onClick={copy} className="absolute top-1.5 right-3 z-10 bg-popover/90 text-subtle">
        {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
      </Button>
      <div
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
        }}
        className="max-h-80 overflow-y-auto py-2 font-mono text-[12px] leading-5"
      >
        {log.length === 0 && <div className="px-4 text-subtle">{running ? "Starting…" : "Nothing was logged."}</div>}
        {log.map((e, i) => (
          <div key={i} className={cn("grid grid-cols-[44px_minmax(0,1fr)] gap-2 px-4", e.level === "error" && "bg-destructive/6", TONE[e.level])}>
            <span className="text-subtle tabular-nums">{clock(e.at)}</span>
            {e.call ? <CallRow e={e} /> : <span className="break-words whitespace-pre-wrap">{e.text}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

function CallRow({ e }: { e: LogEntry }) {
  const c = e.call!
  return (
    <span className="min-w-0">
      <span className="flex items-baseline gap-2">
        <span
          className={cn("size-1.5 shrink-0 translate-y-[-1px] self-center rounded-full", c.status === "ok" ? "bg-free" : c.status === "stopped" ? "bg-warn" : "bg-destructive")}
        />
        <span className="shrink-0">{c.provider}</span>
        <span className="min-w-0 truncate text-muted-foreground">{c.model}</span>
        <span className="shrink-0 text-subtle">
          {c.stage} {c.item}
        </span>
        <span className="ml-auto shrink-0 text-subtle tabular-nums">
          {c.attempt ? `try ${c.attempt} · ` : ""}
          {c.seconds != null ? `${c.seconds.toFixed(1)} s` : ""}
          {c.usd ? ` · ${usd(c.usd)}` : ""}
        </span>
      </span>
      {c.error && <span className="block pl-3.5 break-words whitespace-pre-wrap text-destructive">{c.error}</span>}
    </span>
  )
}
