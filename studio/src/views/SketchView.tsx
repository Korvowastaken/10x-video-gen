import { ArrowLeft, ArrowRight } from "lucide-react"
import { toast } from "sonner"

import { api, type Shot } from "@/api"
import type { Studio } from "@/App"
import { RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { FREE } from "@/lib/progress"
import { ApproveBar, NextStep, NotYet, Page, StepHeader } from "@/views/parts"

const SIZES = [
  { value: "extreme-wide", label: "Extreme wide" },
  { value: "wide", label: "Wide" },
  { value: "medium", label: "Medium" },
  { value: "medium-close-up", label: "Medium close-up" },
  { value: "close-up", label: "Close-up" },
  { value: "extreme-close-up", label: "Extreme close-up" },
  { value: "insert", label: "Insert (an object)" },
  { value: "over-the-shoulder", label: "Over the shoulder" },
]

const LEAD = "A quick frame per scene drawn from shapes: who is where, how close the camera is, and how it moves. Fix the order and framing here, before any picture is drawn."

export function SketchView({ studio }: { studio: Studio }) {
  const { state, flow, track, busy, refresh, go } = studio
  const sb = state.storyboard
  const step = flow.steps.find((s) => s.id === "sketch")!
  const frames = flow.sketch?.frames ?? {}
  const animatic = flow.sketch?.animatic
  const draw = () => track(api.drawSketch())

  async function change(work: () => Promise<unknown>, done: string) {
    try {
      await work()
      toast.success(done)
      await refresh()
      await draw() // free and local, so the frames follow the change at once
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  if (!sb) return <NotYet studio={studio} step="sketch" n={3} title="Sketch" lead={LEAD} needs="The sketch is drawn from the script: one quick frame for each of its scenes." />

  const move = (shot: Shot, by: number) => {
    const order = sb.shots.map((s) => s.id)
    const i = order.indexOf(shot.id)
    ;[order[i], order[i + by]] = [order[i + by], order[i]]
    return change(() => api.reorder(order), `${shot.id} moved`)
  }

  return (
    <Page className="max-w-7xl">
      <StepHeader
        n={3}
        title="Sketch"
        lead={LEAD}
      >
        <RunButton cost={FREE()} disabled={busy || step.locked} onRun={draw}>
          {animatic ? "Draw again" : "Draw the sketch"}
        </RunButton>
        {step.state === "approved" && <NextStep to="References" onClick={() => go("references")} />}
      </StepHeader>
      <ApproveBar studio={studio} step="sketch" what="the sketch" />
      <div className="grid grid-cols-[260px_minmax(0,1fr)] gap-8">
        <aside className="sticky top-[calc(var(--step-head,0px)+24px)] self-start">
          {animatic ? (
            <video key={animatic} src={animatic} controls playsInline className="aspect-[9/16] w-full rounded-lg bg-black ring-1 ring-border" />
          ) : (
            <div className="grid aspect-[9/16] place-items-center rounded-lg border border-dashed px-6 text-center text-[13px] text-subtle">
              The animatic plays every frame for its scene's length. Draw the sketch to see it.
            </div>
          )}
          <p className="mt-2 text-[12px] text-subtle">
            Animatic · {sb.shots.reduce((n, s) => n + s.duration_s, 0)} s. Coloured shapes are people, arrows are movement, a $ marks a paid motion.
          </p>
        </aside>
        <ol className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-x-4 gap-y-6">
          {sb.shots.map((s, i) => (
            <li key={s.id} className="min-w-0">
              <div className="overflow-hidden rounded-md bg-muted ring-1 ring-border">
                {frames[s.id] ? (
                  <img src={frames[s.id]!} alt={`${s.id} sketch: ${s.beat}`} className="aspect-[9/16] w-full object-cover" />
                ) : (
                  <div className="grid aspect-[9/16] place-items-center text-[12px] text-subtle">Not drawn</div>
                )}
              </div>
              <div className="mt-2 flex items-center gap-1">
                <span className="font-mono text-[12.5px] font-medium">{s.id}</span>
                <span className="ml-1 text-[12px] text-subtle tabular-nums">{s.duration_s} s</span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="ml-auto"
                  disabled={busy || step.locked || i === 0}
                  aria-label={`Move ${s.id} earlier`}
                  onClick={() => move(s, -1)}
                >
                  <ArrowLeft />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  disabled={busy || step.locked || i === sb.shots.length - 1}
                  aria-label={`Move ${s.id} later`}
                  onClick={() => move(s, 1)}
                >
                  <ArrowRight />
                </Button>
              </div>
              <Select
                items={SIZES}
                value={s.size}
                disabled={busy || step.locked}
                onValueChange={(v) => change(() => api.saveShot({ ...s, size: String(v) }), `${s.id} framing changed`)}
              >
                <SelectTrigger size="sm" className="mt-1 w-full text-[12px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SIZES.map((z) => (
                    <SelectItem key={z.value} value={z.value}>
                      {z.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="mt-1.5 line-clamp-2 text-[12px] text-muted-foreground">{s.beat}</p>
            </li>
          ))}
        </ol>
      </div>
    </Page>
  )
}
