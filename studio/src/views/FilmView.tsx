import { useState } from "react"
import { toast } from "sonner"

import { api, MODES } from "@/api"
import type { Studio } from "@/App"
import { RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { FREE, PAID, usd } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { Page, Section, StatusDot, StepHeader } from "@/views/parts"

export function FilmView({ studio }: { studio: Studio }) {
  const { state, track, busy, refresh, go } = studio
  const sb = state.storyboard
  const [reason, setReason] = useState(sb?.music.chosen_reason ?? "")
  const report = state.film.report as { duration_s?: number; sources?: Record<string, { used: string; wanted?: string }> }
  const fell = Object.entries(report.sources ?? {}).filter(([, v]) => v.wanted && v.used !== v.wanted)
  const paid = state.shots.filter((s) => s.paid)
  const toBuy = paid.filter((s) => !s.clip)
  const buyPrice = toBuy.reduce((n, s) => n + s.price, 0)
  const voicesPending = state.shots.some((m) => m.lines.some((l, i) => !l.audio || m.stale.voice[i]))

  const cuts = [
    {
      id: "radio",
      label: "Radio cut",
      note: "Voices and placeholder music on black. For a first listen with the family.",
      url: state.film.radio,
      // It records any missing or changed line first, which draws on the free voice limit.
      cost: FREE("Gemini", voicesPending ? "voices" : undefined),
    },
    { id: "rough", label: "Rough cut", note: "Free motion over every still, with voice and captions. No paid clip used.", url: state.film.rough, cost: FREE() },
    {
      id: "final",
      label: "Final film",
      note: `9:16 and 16:9, using the ${paid.length - toBuy.length} clip${paid.length - toBuy.length === 1 ? "" : "s"} you bought. Nothing new is bought.`,
      url: state.film.vertical,
      cost: FREE(),
    },
  ] as const
  const videos = [
    { id: "vertical", label: "Final 9:16", url: state.film.vertical, portrait: true },
    { id: "wide", label: "Final 16:9", url: state.film.wide, portrait: false },
    { id: "rough", label: "Rough cut", url: state.film.rough, portrait: true },
    { id: "radio", label: "Radio cut", url: state.film.radio, portrait: true },
  ].filter((v) => v.url)
  const [watch, setWatch] = useState(videos[0]?.id ?? "")
  const video = videos.find((v) => v.id === watch) ?? videos[0]

  return (
    <Page>
      <StepHeader n={4} title="Film" lead="Cut the scenes together and watch. Every cut here is free: it only uses what is already made." />

      <div className="grid grid-cols-[minmax(0,1fr)_340px] gap-10">
        <div className="min-w-0">
          <div className="divide-y rounded-lg border">
            {cuts.map((c) => (
              <div key={c.id} className="flex items-center gap-4 px-4 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-3">
                    <span className="font-medium">{c.label}</span>
                    {c.url ? (
                      state.film.stale ? (
                        <StatusDot status="stale">Older than your edits</StatusDot>
                      ) : (
                        <StatusDot status="ok">Made</StatusDot>
                      )
                    ) : (
                      <StatusDot status="missing">Not made yet</StatusDot>
                    )}
                  </div>
                  <p className="mt-0.5 text-[12.5px] text-muted-foreground">{c.note}</p>
                </div>
                <RunButton
                  variant={c.id === "rough" ? "default" : "secondary"}
                  cost={c.cost}
                  disabled={busy || !sb}
                  onRun={() => track(api.run(c.id))}
                >
                  {c.url ? "Make again" : "Make"}
                </RunButton>
              </div>
            ))}
          </div>

          {report.duration_s && (
            <p className="mt-3 text-[12.5px] text-muted-foreground">
              Last final cut: {report.duration_s.toFixed(1)} s.{" "}
              {fell.length
                ? `${fell.length} scene${fell.length > 1 ? "s" : ""} used free motion instead of a clip: ${fell.map(([k, v]) => `${k} (${MODES[v.used]?.label ?? v.used})`).join(", ")}.`
                : "Every scene got its planned motion."}
            </p>
          )}

          <Section
            title="Paid clips"
            aside={<span className="text-[12px] text-subtle">{paid.length} scenes are planned with a WaveSpeed clip</span>}
            className="mt-10"
          >
            <div className="flex flex-wrap gap-1.5">
              {paid.map((s) => (
                <button
                  key={s.id}
                  onClick={() => go("scenes", s.id)}
                  className={cn(
                    "rounded-md border px-2.5 py-1 font-mono text-[12px] transition-colors hover:bg-muted",
                    s.clip ? "text-secondary-foreground" : "border-paid/30 text-paid",
                  )}
                  title={s.clip ? "Bought" : `${usd(s.price)} to buy`}
                >
                  {s.id} {s.clip ? "✓" : usd(s.price)}
                </button>
              ))}
            </div>
            {toBuy.length > 0 ? (
              <div className="mt-3 flex items-center gap-3">
                <RunButton
                  cost={PAID(buyPrice)}
                  spent={state.spent}
                  what={`${toBuy.length} clips (${toBuy.map((s) => s.id).join(", ")}).`}
                  confirm={{ title: "", body: null, action: `Buy ${toBuy.length} clips` }}
                  disabled={busy}
                  onRun={() => track(api.run("shots", { max_paid: toBuy.length }))}
                >
                  Buy {toBuy.length} missing clips
                </RunButton>
                <span className="text-[12px] text-subtle">Or buy them one at a time from each scene, after you like its still.</span>
              </div>
            ) : (
              <p className="mt-3 text-[12.5px] text-muted-foreground">All clips are bought.</p>
            )}
          </Section>

          {sb && (
            <Section title="Score" aside={<span className="text-[12px] text-subtle">Pick the music for the final film</span>} className="mt-10">
              <p className="-mt-1 mb-3 max-w-2xl text-[12.5px] text-muted-foreground">{sb.music.caption}</p>
              <div className="divide-y rounded-lg border">
                {sb.music.seeds.map((seed, i) => {
                  const url = state.music[i]
                  const on = sb.music.chosen === i
                  return (
                    <div key={seed} className="flex items-center gap-4 px-4 py-2.5">
                      <span className="w-24 text-[13px] font-medium">Candidate {i + 1}</span>
                      {url ? <audio controls src={url} className="h-8 min-w-0 flex-1" /> : <span className="flex-1 text-[12.5px] text-subtle">Not made yet</span>}
                      <Button
                        size="sm"
                        variant={on ? "default" : "secondary"}
                        disabled={!url}
                        onClick={async () => {
                          await api.chooseMusic(i, reason)
                          toast.success(`Candidate ${i + 1} chosen`)
                          refresh()
                        }}
                      >
                        {on ? "Chosen" : "Choose"}
                      </Button>
                    </div>
                  )
                })}
              </div>
              <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why this one? Saved with your choice." className="mt-3" />
              <div className="mt-3">
                {state.music_price > 0 ? (
                  <RunButton
                    cost={PAID(state.music_price)}
                    spent={state.spent}
                    what={`${state.music.filter((u) => !u).length} score candidates from ACE-Step.`}
                    confirm={{ title: "", body: null, action: "Make candidates" }}
                    disabled={busy}
                    onRun={() => track(api.run("music"))}
                  >
                    Make score candidates
                  </RunButton>
                ) : (
                  <span className="text-[12.5px] text-muted-foreground">All candidates are made.</span>
                )}
              </div>
            </Section>
          )}
        </div>

        <aside className="sticky top-8 self-start">
          {video ? (
            <>
              {videos.length > 1 && (
                <ToggleGroup value={[video.id]} onValueChange={(v) => v[0] && setWatch(v[0])} variant="outline" size="sm" spacing={0} className="mb-2 w-full">
                  {videos.map((v) => (
                    <ToggleGroupItem key={v.id} value={v.id} className="flex-1">
                      {v.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              )}
              <div className={cn("overflow-hidden rounded-lg bg-black ring-1 ring-border", video.portrait ? "aspect-[9/16]" : "aspect-video")}>
                <video key={video.url} src={video.url!} controls playsInline className="size-full object-contain" />
              </div>
            </>
          ) : (
            <div className="grid aspect-[9/16] place-items-center rounded-lg border border-dashed px-8 text-center text-[13px] text-subtle">
              No cut yet. Make a rough cut to watch the film so far.
            </div>
          )}
        </aside>
      </div>
    </Page>
  )
}
