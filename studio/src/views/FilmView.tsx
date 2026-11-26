import { useEffect, useState } from "react"
import { toast } from "sonner"

import { api, MODES, type Storyboard } from "@/api"
import type { Studio } from "@/App"
import { ProvidersPanel } from "@/components/providers-panel"
import { useTaskCost } from "@/lib/models"
import { RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { FREE, flowStep, PAID, scene, usd, VIEW_OF } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { BudgetButton, Filmstrip, FlowContext, SceneWorkspace, toneOf } from "@/views/SceneEditor"
import { ApproveBar, NextStep, NotYet, Section, StatusDot, StepHeader } from "@/views/parts"

const LEAD = "Make and approve each scene, then cut the film in 9:16 and 16:9. Cutting is free: it only uses what is already made."

/** Scenes and the cut on one page, laid out like an editor: the picture in the middle, its settings on the right,
 * and every scene in a strip along the bottom. The cut is the first tile of the strip. */
export function FilmView({ studio, onScene }: { studio: Studio; onScene: (id: string) => void }) {
  const sb = studio.state.storyboard
  const [picked, setPicked] = useState<string[]>([])
  const make = useTaskCost(studio, ["image"], "pictures")
  // The strip's order, the cut first. Arrow keys step through it, unless you are typing.
  const order = ["", ...(sb?.shots.map((s) => s.id) ?? [])]
  const at = Math.max(0, order.indexOf(studio.scene))
  useKeys(order[at - 1], order[at + 1], onScene)
  if (!sb || !sb.shots.length)
    return (
      <NotYet
        studio={studio}
        step="scenes"
        n={4}
        title="Film"
        lead={LEAD}
        needs="The scenes come from the script, and each is drawn from the approved references."
      />
    )

  const { flow, state, busy } = studio
  const shot = sb.shots.find((s) => s.id === studio.scene)
  const rows = sb.shots.map((s) => ({
    s,
    flow: flow.scenes.find((x) => x.id === s.id),
    status: scene(state.shots.find((x) => x.id === s.id)!),
  }))
  const tones = rows.map((r) => toneOf(r.flow, r.status))
  const count = (t: string) => tones.filter((x) => x === t).length

  const toBuy = state.shots.filter((m) => scene(m).toBuy)
  const buying = toBuy.length ? `, ${toBuy.length} clips to buy (${usd(toBuy.reduce((n, m) => n + m.price, 0))})` : ""
  const scenesStep = flowStep(flow, "scenes")
  const current = flow.steps.find((s) => !s.locked && s.state !== "approved")
  // Not made yet, or out of date: what "make all" picks up. Making only redraws what changed.
  const unmade = rows.filter((r) => !r.flow?.preview || r.status.needsWork).map((r) => r.s.id)
  const film = state.film
  const made = film.vertical ?? film.rough ?? film.radio
  const cut = {
    note: !made ? "Not made yet" : film.stale ? "Older than your edits" : film.vertical ? "Final film made" : "Rough cut made",
    stale: !!(made && film.stale),
  }

  function makeMany(ids: string[]) {
    return studio.track(api.makeScenes(ids)).then((job) => job && setPicked([]))
  }

  return (
    <FlowContext.Provider value={flow}>
      <div className="flex h-screen flex-col">
        <StepHeader
          n={4}
          title="Film"
          lead={`${count("weave-done")} of ${sb.shots.length} scenes approved, ${count("weave-stale")} need you${buying}. Approve every scene to make the final cut.`}
          className="mt-0 mb-0 shrink-0 px-8 pt-5 pb-4"
        >
          <RunButton variant="secondary" cost={make} disabled={busy || scenesStep.locked || !picked.length} onRun={() => makeMany(picked)}>
            {picked.length ? `Make ${picked.length} picked` : "Make picked"}
          </RunButton>
          <RunButton cost={make} disabled={busy || scenesStep.locked || !unmade.length} onRun={() => makeMany(unmade)}>
            {unmade.length ? `Make all unmade (${unmade.length})` : "All scenes made"}
          </RunButton>
          <BudgetButton studio={studio} />
          {scenesStep.locked && current && <NextStep to={current.title} onClick={() => studio.go(VIEW_OF[current.id])} />}
        </StepHeader>
        <div className="flex min-h-0 flex-1">
          {shot ? (
            <SceneWorkspace
              key={shot.id}
              studio={studio}
              shot={shot}
              media={state.shots.find((s) => s.id === shot.id)!}
              prev={order[at - 1] || undefined}
              next={order[at + 1]}
              onScene={onScene}
            />
          ) : (
            <CutPanel studio={studio} sb={sb} onScene={onScene} />
          )}
        </div>
        <Filmstrip studio={studio} selected={shot?.id ?? ""} onSelect={onScene} picked={picked} onPick={setPicked} cut={cut} />
      </div>
    </FlowContext.Provider>
  )
}

/** The cut: radio, rough and final, what each scene uses, the paid clips and the score. */
function CutPanel({ studio, sb, onScene }: { studio: Studio; sb: Storyboard; onScene: (id: string) => void }) {
  const { state, flow, track, busy, refresh } = studio
  const locked = flowStep(flow, "final").locked
  const [reason, setReason] = useState(sb?.music.chosen_reason ?? "")
  const report = state.film.report as {
    duration_s?: number
    sources?: Record<string, { used: string; wanted?: string }>
  }
  const fell = Object.entries(report.sources ?? {}).filter(([, v]) => v.wanted && v.used !== v.wanted)
  const paid = state.shots.filter((s) => s.paid)
  const toBuy = paid.filter((s) => !s.clip)
  const buyPrice = toBuy.reduce((n, s) => n + s.price, 0)
  const voicesPending = state.shots.some((m) => m.lines.some((l, i) => !l.audio || m.stale.voice[i]))
  const record = useTaskCost(studio, ["tts"], "voices")

  const cuts = [
    {
      id: "radio",
      label: "Radio cut",
      note: "Voices and placeholder music on black. For a first listen with the family.",
      url: state.film.radio,
      // It records any missing or changed line first, which draws on the free voice limit.
      cost: voicesPending ? record : FREE(),
    },
    {
      id: "rough",
      label: "Rough cut",
      note: "Free motion over every still, with voice and captions. No paid clip used.",
      url: state.film.rough,
      cost: FREE(),
    },
    {
      id: "final",
      label: "Final film",
      note: `9:16 and 16:9, using the ${paid.length - toBuy.length} clip${paid.length - toBuy.length === 1 ? "" : "s"} you bought. Nothing new is bought.`,
      url: state.film.vertical,
      cost: FREE(),
    },
  ] as const
  const videos = [
    {
      id: "vertical",
      label: "Final 9:16",
      url: state.film.vertical,
      portrait: true,
    },
    { id: "wide", label: "Final 16:9", url: state.film.wide, portrait: false },
    { id: "rough", label: "Rough cut", url: state.film.rough, portrait: true },
    { id: "radio", label: "Radio cut", url: state.film.radio, portrait: true },
  ].filter((v) => v.url)
  const [watch, setWatch] = useState(videos[0]?.id ?? "")
  const video = videos.find((v) => v.id === watch) ?? videos[0]

  return (
    <>
      <section aria-label="The film" className="flex min-w-0 flex-1 flex-col items-center justify-center gap-3 bg-muted/40 px-16 py-6">
        {video ? (
          <>
            {videos.length > 1 && (
              <ToggleGroup
                value={[video.id]}
                onValueChange={(v) => v[0] && setWatch(v[0])}
                variant="outline"
                size="sm"
                spacing={0}
                className="shrink-0 bg-background"
              >
                {videos.map((v) => (
                  <ToggleGroupItem key={v.id} value={v.id} className="px-3">
                    {v.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            )}
            <div className="flex min-h-0 w-full flex-1 items-center justify-center">
              <div
                className={cn(
                  "max-h-full max-w-full overflow-hidden rounded-lg bg-black shadow-lg ring-1 ring-border",
                  video.portrait ? "aspect-[9/16] h-full" : "aspect-video w-full",
                )}
              >
                <video key={video.url} src={video.url!} controls playsInline className="size-full object-contain" />
              </div>
            </div>
          </>
        ) : (
          <div className="grid aspect-[9/16] h-full max-h-full place-items-center rounded-lg border border-dashed px-8 text-center text-[13px] text-subtle">
            No cut yet. Make a rough cut to watch the film so far.
          </div>
        )}
      </section>

      <aside aria-label="The cut" className="w-[420px] shrink-0 overflow-y-auto border-l px-6 pt-5 pb-16">
        <ProvidersPanel studio={studio} step="film" />
        <h2 className="mb-4 text-xl font-semibold tracking-tight">The cut</h2>
        <ApproveBar studio={studio} step="final" what="the final cut" />
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
                  disabled={busy || (c.id === "final" && locked)}
                  onRun={() => track(c.id === "final" ? api.makeCut() : api.run(c.id))}
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

          <CutChoices studio={studio} sb={sb} />

          <Section
            title="Paid clips"
            aside={<span className="text-[12px] text-subtle">{paid.length} scenes are planned with a WaveSpeed clip</span>}
            className="mt-10"
          >
            <div className="flex flex-wrap gap-1.5">
              {paid.map((s) => (
                <button
                  key={s.id}
                  onClick={() => onScene(s.id)}
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
                  confirm={{
                    title: "",
                    body: null,
                    action: `Buy ${toBuy.length} clips`,
                  }}
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
                      {url ? (
                        <audio controls src={url} className="h-8 min-w-0 flex-1" />
                      ) : (
                        <span className="flex-1 text-[12.5px] text-subtle">Not made yet</span>
                      )}
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
                    confirm={{
                      title: "",
                      body: null,
                      action: "Make candidates",
                    }}
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
      </aside>
    </>
  )
}

/** Left and right arrows step through the strip, unless you are typing. */
function useKeys(prev: string | undefined, next: string | undefined, go: (id: string) => void) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
      const el = e.target as HTMLElement
      if (el.closest("input, textarea, select, [contenteditable=true], [role=slider], audio, video")) return
      if (e.key === "ArrowLeft" && prev !== undefined) go(prev)
      else if (e.key === "ArrowRight" && next !== undefined) go(next)
      else return
      e.preventDefault()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [prev, next, go])
}

/** Per scene, what goes into the cut: its own mode, or a free one instead (a bought clip is kept either way). */
function CutChoices({ studio, sb }: { studio: Studio; sb: Storyboard }) {
  const { flow, refresh, busy } = studio
  const use = sb.edit?.use ?? {}
  const free = Object.entries(flow.catalog.modes).filter(([, m]) => !m.paid)

  async function choose(id: string, mode: string) {
    try {
      await api.setCut({ ...use, [id]: mode })
      toast.success(`${id} will use ${flow.catalog.modes[mode]?.label ?? mode} in the cut`)
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Section
      title="What each scene uses"
      aside={<span className="text-[12px] text-subtle">Only approved scenes go in; free modes never cost anything</span>}
      className="mt-10"
    >
      <div className="grid grid-cols-2 gap-2">
        {sb.shots.map((s) => {
          const own = s.motion.mode
          const current = use[s.id] ?? own
          const fs = flow.scenes.find((x) => x.id === s.id)
          const items = [
            {
              value: own,
              label: `${flow.catalog.modes[own]?.label ?? own} (planned)`,
            },
            ...free.filter(([id]) => id !== own).map(([id, m]) => ({ value: id, label: m.label })),
          ]
          return (
            <div key={s.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5">
              <span className="font-mono text-[12px] font-medium">{s.id}</span>
              <span
                className={cn(
                  "size-1.5 shrink-0 rounded-full",
                  fs?.state === "approved" ? "bg-free" : fs?.state === "stale" ? "bg-warn" : "border border-subtle",
                )}
                title={fs?.state === "approved" ? "Approved" : "Not approved yet"}
              />
              <Select items={items} value={current} disabled={busy} onValueChange={(v) => choose(s.id, String(v))}>
                <SelectTrigger size="sm" className="ml-auto h-7 min-w-0 flex-1 border-none text-[12px] shadow-none">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {items.map((i) => (
                    <SelectItem key={i.value} value={i.value}>
                      {i.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )
        })}
      </div>
    </Section>
  )
}
