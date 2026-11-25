import { ArrowRight, Check, Lock, RefreshCw } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { api, type FlowStepId } from "@/api"
import type { Studio } from "@/App"
import { Button } from "@/components/ui/button"
import { upper } from "@/lib/progress"
import { cn } from "@/lib/utils"

export function Page({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mx-auto w-full max-w-6xl px-10 pt-8 pb-28", className)}>{children}</div>
}

/**
 * Step number, title and one line on what this step is for. It stays pinned to the top while the step scrolls,
 * and publishes its height as --step-head so sticky side panels can sit just under it.
 */
export function StepHeader({ n, title, lead, className, children }: { n: number; title: string; lead: string; className?: string; children?: React.ReactNode }) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const root = document.documentElement
    const set = () => root.style.setProperty("--step-head", `${el.offsetHeight}px`)
    set()
    const watch = new ResizeObserver(set)
    watch.observe(el)
    return () => {
      watch.disconnect()
      root.style.removeProperty("--step-head")
    }
  }, [])
  return (
    <header
      ref={ref}
      className={cn("sticky top-0 z-30 -mt-8 mb-6 flex items-center gap-8 border-b bg-background/95 pt-8 pb-5 backdrop-blur", className)}
    >
      <div className="min-w-0 flex-1">
        <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.01em]">{title}</h1>
        <p className="mt-1 max-w-2xl text-muted-foreground">
          <span className="text-subtle tabular-nums">Step {n} of 6 · </span>
          {lead}
        </p>
      </div>
      {children && <div className="flex shrink-0 items-center gap-3">{children}</div>}
    </header>
  )
}

/** The way on to the next step, set apart from the step's own buttons by a rule. */
export function NextStep({ to, onClick }: { to: string; onClick: () => void }) {
  return (
    <>
      <span aria-hidden className="mx-1 h-7 w-px bg-border" />
      <Button onClick={onClick}>
        Go to {to} <ArrowRight />
      </Button>
    </>
  )
}

export type Status = "ok" | "stale" | "missing" | "paid"

/** A small status label: up to date, out of date, not made, or to buy. */
export function StatusDot({ status, children, className }: { status: Status; children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-[12px]",
        status === "ok" && "text-subtle",
        status === "stale" && "text-warn",
        status === "missing" && "text-muted-foreground",
        status === "paid" && "text-paid",
        className,
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          status === "ok" && "bg-free",
          status === "stale" && "bg-warn",
          status === "missing" && "border border-current",
          status === "paid" && "bg-paid",
        )}
      />
      {children}
    </span>
  )
}

export function Section({ title, aside, children, className }: { title: string; aside?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("mt-8", className)}>
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-[13px] font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  )
}

/**
 * Where this step stands and the one button that moves the film on: Approve.
 * Stale shows what changed since the approval; a step that is not ready says what is missing.
 */
export function ApproveBar({ studio, step, what, scene }: { studio: Studio; step: FlowStepId; what: string; scene?: string }) {
  const { flow, refresh } = studio
  const [saving, setSaving] = useState(false)
  const s = flow.steps.find((x) => x.id === step)!
  const one = scene ? flow.scenes.find((x) => x.id === scene) : undefined
  const state = one ? one.state : s.state
  const changed = one ? one.changed : s.changed
  const blockers = s.locked ? [] : one ? one.blockers : s.blockers
  const before = flow.steps[flow.steps.findIndex((x) => x.id === step) - 1]

  async function set(approve: boolean) {
    setSaving(true)
    try {
      await (approve ? api.approve(step, scene) : api.unapprove(step, scene))
      if (approve) toast.success(`${upper(what)} approved`)
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className={cn(
        "mb-6 flex min-h-12 items-center gap-3 rounded-md border px-4 py-2 text-[13px]",
        state === "approved" && !s.locked && "border-free/30 bg-free/8",
        state === "stale" && "border-warn/35 bg-warn/8",
        !s.locked && state !== "approved" && state !== "stale" && !blockers.length && "border-gold/60 bg-gold/10",
      )}
    >
      {s.locked ? (
        <Lock className="size-4 shrink-0 text-subtle" />
      ) : state === "approved" ? (
        <Check className="size-4 shrink-0 text-free" strokeWidth={2.5} />
      ) : state === "stale" ? (
        <RefreshCw className="size-3.5 shrink-0 text-warn" strokeWidth={2.5} />
      ) : (
        <span className={cn("size-2.5 shrink-0 rounded-full", blockers.length ? "border border-thread" : "bg-gold")} />
      )}
      <div className="min-w-0 flex-1">
        {s.locked ? (
          <span className="text-muted-foreground">Locked until {before?.title} is approved. You can look, but not change anything yet.</span>
        ) : state === "approved" ? (
          <span>{upper(what)} is approved.</span>
        ) : state === "stale" ? (
          <span>
            <span className="font-medium text-warn">Changed since you approved it:</span> {changed.join(", ")}. Check it, then approve again.
          </span>
        ) : blockers.length ? (
          <span className="text-muted-foreground">Before you can approve: {blockers.join("; ")}.</span>
        ) : (
          <span>Looks right? Approve {what} to open the next step.</span>
        )}
      </div>
      {!s.locked &&
        (state === "approved" ? (
          <Button size="sm" variant="ghost" className="text-subtle" disabled={saving} onClick={() => set(false)}>
            Undo approval
          </Button>
        ) : (
          <Button size="sm" disabled={saving || blockers.length > 0} onClick={() => set(true)}>
            <Check /> Approve {what}
          </Button>
        ))}
    </div>
  )
}
