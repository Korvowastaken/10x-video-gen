import { cn } from "@/lib/utils"

export function Page({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mx-auto w-full max-w-6xl px-10 pt-8 pb-28", className)}>{children}</div>
}

/** Step number, title and one line on what this step is for. */
export function StepHeader({ n, title, lead, children }: { n: number; title: string; lead: string; children?: React.ReactNode }) {
  return (
    <header className="mb-7 flex items-end gap-6">
      <div className="min-w-0 flex-1">
        <div className="mb-1 text-[12px] text-subtle tabular-nums">Step {n} of 4</div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 max-w-2xl text-muted-foreground">{lead}</p>
      </div>
      {children}
    </header>
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
