import { useState } from "react"
import { toast } from "sonner"

import { api } from "@/api"
import type { Studio } from "@/App"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

const CUTS = [
  { id: "radio", label: "Radio cut", note: "voice + placeholder music on black, for the first audience test" },
  { id: "rough", label: "Rough cut", note: "free motion over the stills, no paid clips" },
  { id: "final", label: "Final film", note: "clips where bought, 9:16 and 16:9, about 10 minutes" },
] as const

export function FilmView({ studio }: { studio: Studio }) {
  const { state, track, busy, refresh } = studio
  const sb = state.storyboard
  const [reason, setReason] = useState(sb?.music.chosen_reason ?? "")
  const report = state.film.report as { duration_s?: number; sources?: Record<string, { used: string; wanted?: string }> }
  const fell = Object.entries(report.sources ?? {}).filter(([, v]) => v.wanted && v.used !== v.wanted)

  return (
    <div className="mx-auto max-w-5xl px-5 py-10 md:px-10">
      <div className="mb-1 font-mono text-[11px] tracking-widest text-subtle uppercase">Assemble</div>
      <h1 className="mb-6 text-3xl font-semibold tracking-tight">Film</h1>
      <div className="grid gap-3 md:grid-cols-3">
        {CUTS.map((c) => (
          <div key={c.id} className="flex flex-col rounded-xl border bg-card p-4">
            <div className="font-medium">{c.label}</div>
            <p className="mt-1 mb-4 flex-1 text-[12.5px] text-muted-foreground">{c.note}</p>
            <Button variant={c.id === "final" ? "default" : "secondary"} disabled={busy || !sb} onClick={() => track(api.run(c.id))}>
              Make {c.label.toLowerCase()}
            </Button>
          </div>
        ))}
      </div>

      <div className="mt-10 grid gap-6 md:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <Video label="Vertical 9:16" url={state.film.vertical ?? state.film.rough ?? state.film.radio} portrait />
        <div className="space-y-6">
          <Video label="Horizontal 16:9" url={state.film.wide} />
          {report.duration_s && (
            <p className="text-[13px] text-muted-foreground">
              Last final cut: {report.duration_s.toFixed(1)} s.{" "}
              {fell.length ? `${fell.length} scene(s) fell back: ${fell.map(([k, v]) => `${k} → ${v.used}`).join(", ")}.` : "Every scene got its planned motion."}
            </p>
          )}
        </div>
      </div>

      {sb && (
        <section className="mt-12">
          <h2 className="mb-3 text-[13px] font-semibold text-muted-foreground">Score</h2>
          <div className="grid gap-2">
            {sb.music.seeds.map((seed, i) => {
              const url = state.music[i]
              return (
                <div key={seed} className={cn("flex flex-wrap items-center gap-3 rounded-xl border bg-card p-3", sb.music.chosen === i && "border-primary")}>
                  <span className="w-28 text-[13px] font-medium">Candidate {i + 1}</span>
                  {url ? <audio controls src={url} className="h-8 min-w-0 flex-1" /> : <span className="flex-1 text-[12.5px] text-subtle">not made yet</span>}
                  <Button
                    size="sm"
                    variant={sb.music.chosen === i ? "default" : "secondary"}
                    disabled={!url}
                    onClick={async () => {
                      await api.chooseMusic(i, reason)
                      toast.success(`Candidate ${i + 1} chosen`)
                      refresh()
                    }}
                  >
                    {sb.music.chosen === i ? "Chosen" : "Choose"}
                  </Button>
                </div>
              )
            })}
          </div>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why this one? (goes into storyboard.json)" className="mt-3" />
          <Button variant="secondary" className="mt-3" disabled={busy} onClick={() => track(api.run("music"))}>
            Make candidates · about $0.07
          </Button>
        </section>
      )}
    </div>
  )
}

function Video({ label, url, portrait }: { label: string; url: string | null; portrait?: boolean }) {
  return (
    <figure>
      <div className={cn("overflow-hidden rounded-xl border bg-secondary", portrait ? "aspect-[9/16]" : "aspect-video")}>
        {url ? <video src={url} controls playsInline className="size-full bg-black object-contain" /> : <div className="grid size-full place-items-center text-[12px] text-subtle">not made yet</div>}
      </div>
      <figcaption className="mt-2 text-[12px] text-subtle">{label}</figcaption>
    </figure>
  )
}
