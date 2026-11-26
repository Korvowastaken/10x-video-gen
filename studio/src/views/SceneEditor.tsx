import { Check, ChevronLeft, ChevronRight, Clapperboard } from "lucide-react"
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { ApiError, api, MODES, type Flow, type Job, type Shot, type ShotState, type Tune } from "@/api"
import type { Studio } from "@/App"
import { TaskPicker } from "@/components/providers-panel"
import { useTaskCost, useTaskCosts } from "@/lib/models"
import { RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { LimitsContext } from "@/lib/limits"
import { affected, back, blocked, FREE, flowStep, PAID, scene, usd, type Cost, type Part } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { ApproveBar, StatusDot } from "@/views/parts"
import { clean, same, VoiceLines } from "@/views/VoiceTune"

/** The flow, for the motion picker deep in the editor: prices and the allowed modes. */
export const FlowContext = createContext<Flow | null>(null)

/** The Film page's strip along the bottom: the cut first, then every scene in film order. Click one to open it; tick it to make it with others. */
export function Filmstrip({
  studio,
  selected,
  onSelect,
  picked,
  onPick,
  cut,
}: {
  studio: Studio
  selected: string
  onSelect: (id: string) => void
  picked: string[]
  onPick: (ids: string[]) => void
  /** How the cut stands, under its tile ("Not made yet", "Made"...). */
  cut: { note: string; stale: boolean }
}) {
  const sb = studio.state.storyboard!
  const [filter, setFilter] = useState<"all" | "work">("all")
  const rows = sb.shots.map((s, i) => {
    const m = studio.state.shots.find((x) => x.id === s.id)!
    const status = scene(m)
    const f = studio.flow.scenes.find((x) => x.id === s.id)
    return { s, m, i, status, f, tone: toneOf(f, status) }
  })
  const work = rows.filter((r) => r.status.needsWork).length
  const shown = filter === "work" ? rows.filter((r) => r.status.needsWork) : rows
  const picking = picked.length > 0
  const allPicked = shown.length > 0 && shown.every((r) => picked.includes(r.s.id))

  // Keep the open scene in view as you step through.
  useEffect(() => {
    document.getElementById(`strip-${selected || "cut"}`)?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
      behavior: "smooth",
    })
  }, [selected])

  return (
    <nav aria-label="Scenes" className="flex shrink-0 items-stretch gap-4 border-t bg-card px-5 py-3">
      <div className="flex w-[148px] shrink-0 flex-col justify-center gap-2">
        <ToggleGroup
          value={[filter]}
          onValueChange={(v) => v[0] && setFilter(v[0] as "all" | "work")}
          variant="outline"
          size="sm"
          spacing={0}
          className="w-full"
        >
          <ToggleGroupItem value="all" className="flex-1">
            All
          </ToggleGroupItem>
          <ToggleGroupItem value="work" className="flex-1">
            Redo <span className={cn("tabular-nums", work ? "text-warn" : "text-subtle")}>{work}</span>
          </ToggleGroupItem>
        </ToggleGroup>
        <label className="flex items-center gap-2 text-[11.5px] text-subtle">
          <Checkbox
            checked={allPicked}
            indeterminate={shown.some((r) => picked.includes(r.s.id)) && !allPicked}
            disabled={!shown.length}
            onCheckedChange={(on) =>
              onPick(on ? [...new Set([...picked, ...shown.map((r) => r.s.id)])] : picked.filter((id) => !shown.some((r) => r.s.id === id)))
            }
          />
          {picking ? `${picked.length} picked` : "Pick to make"}
        </label>
      </div>
      <span aria-hidden className="w-px shrink-0 bg-border" />
      <div className="flex min-w-0 flex-1 items-end gap-2.5 overflow-x-auto pb-0.5">
        <button
          id="strip-cut"
          onClick={() => onSelect("")}
          aria-current={selected === "" ? "page" : undefined}
          title={`The cut: ${cut.note}`}
          className="group flex shrink-0 flex-col items-center gap-1.5"
        >
          <span
            className={cn(
              "grid h-[84px] w-[52px] place-items-center rounded-md bg-secondary ring-1 ring-border transition",
              selected === "" ? "ring-2 ring-foreground" : "opacity-80 group-hover:opacity-100",
            )}
          >
            <Clapperboard className="size-5 text-muted-foreground" />
          </span>
          <span className={cn("text-[11.5px] font-medium", cut.stale ? "text-warn" : selected === "" ? "text-foreground" : "text-subtle")}>Cut</span>
        </button>
        <span aria-hidden className="mx-1 h-[84px] w-px shrink-0 self-start bg-border" />
        {shown.length === 0 && <p className="self-center text-[12.5px] text-subtle">Nothing needs a redo.</p>}
        {shown.map(({ s, m, i, status, f, tone }) => {
          const on = selected === s.id
          const isPicked = picked.includes(s.id)
          return (
            <div key={s.id} id={`strip-${s.id}`} className="group relative flex shrink-0 flex-col items-center gap-1.5">
              <button
                onClick={() => onSelect(s.id)}
                aria-current={on ? "page" : undefined}
                aria-label={`${s.id}: ${TONE_WORD[tone]}`}
                title={`${s.id} · ${s.lines[0]?.en ?? s.beat}`}
                className={cn(
                  "relative h-[84px] w-[52px] overflow-hidden rounded-md bg-secondary ring-1 ring-border transition",
                  on ? "ring-2 ring-foreground" : "opacity-80 group-hover:opacity-100",
                )}
              >
                {m.keyframe && <img src={m.keyframe} alt="" className={cn("size-full object-cover", status.stale.includes("keyframe") && "opacity-60")} />}
                {MODES[s.motion.mode]?.paid && <span className="absolute right-1 bottom-1 size-1.5 rounded-full bg-paid" title="Paid clip" />}
              </button>
              <Checkbox
                aria-label={`Pick ${s.id}`}
                checked={isPicked}
                onCheckedChange={(v) => onPick(v ? [...picked, s.id] : picked.filter((id) => id !== s.id))}
                className={cn(
                  "absolute top-1 left-1 bg-background/80 backdrop-blur transition-opacity",
                  isPicked || picking ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
                )}
              />
              <span className={cn("flex items-center gap-1 text-[11.5px] tabular-nums", on ? "font-semibold text-foreground" : "text-subtle")}>
                {f?.state === "approved" && <Check className="size-3 text-free" strokeWidth={3} />}
                {tone === "weave-stale" && <span className="size-1.5 rounded-full bg-warn" />}
                {i + 1}
              </span>
            </div>
          )
        })}
      </div>
    </nav>
  )
}

type Draft = (fn: (s: Shot) => void) => void

const PARTS: Part[] = ["keyframe", "voice", "clip"]
const NAME: Record<Part, string> = { keyframe: "still", voice: "voice", clip: "clip" }
type Tone = "ok" | "stale" | "missing" | "paid"

/**
 * One scene: the picture in the middle, and on the right everything that can change about it in one
 * place. Each part (still, voice, motion) holds its own fields and model, and a tick to redo it. The
 * redo at the bottom saves the edits, lets the writer rewrite the ticked parts from the note, and
 * remakes them.
 */
export function SceneWorkspace({
  studio,
  shot,
  media,
  prev,
  next,
  onScene,
}: {
  studio: Studio
  shot: Shot
  media: ShotState
  prev?: string
  next?: string
  onScene: (id: string) => void
}) {
  const { busy, flow } = studio
  const sb = studio.state.storyboard!
  const cast = useMemo(() => Object.fromEntries(sb.characters.map((c) => [c.id, c])), [sb.characters])
  const speakers = useMemo(() => [...new Set(shot.lines.map((l) => l.speaker))], [shot.lines])
  const savedVoices = useMemo(() => Object.fromEntries(speakers.map((id) => [id, cast[id]?.voice.tune ?? {}])), [speakers, cast])

  const [draft, setDraft] = useState<Shot>(shot)
  const [voices, setVoices] = useState<Record<string, Tune>>(savedVoices)
  const [note, setNote] = useState("")
  const [picked, setPicked] = useState<Partial<Record<Part, boolean>>>({})
  const [errors, setErrors] = useState<string[]>([])
  /** Set when a redo finished: take the scene as saved, whatever the draft holds. */
  const resync = useRef(false)

  const shotDirty = JSON.stringify(draft) !== JSON.stringify(shot)
  const changedVoices = speakers.filter((id) => !same(voices[id], savedVoices[id]))
  const dirty = shotDirty || changedVoices.length > 0
  useEffect(() => {
    if (dirty && !resync.current) return
    resync.current = false
    setDraft(shot)
    setVoices(savedVoices)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shot, savedVoices])

  const set: Draft = (fn) =>
    setDraft((p) => {
      const n = structuredClone(p)
      fn(n)
      return n
    })

  // What each part needs, and which start ticked: out of date, never made, or edited. Never the paid clip.
  const status = scene(media)
  const flowScene = flow.scenes.find((s) => s.id === shot.id)
  const made = !!flowScene?.preview
  const paidMode = !!MODES[draft.motion.mode]?.paid
  const edited = affected(shot, draft, true)
  const wordsStale = media.stale.voice.some((s, i) => s && !media.lines[i]?.tunable)
  const untuned = shot.lines.some((_, i) => media.lines[i]?.previewable && !same(media.lines[i].applied, media.lines[i].tune))
  const tuneEdited = changedVoices.length > 0 || JSON.stringify(draft.lines.map((l) => l.tune ?? null)) !== JSON.stringify(shot.lines.map((l) => l.tune ?? null))
  const auto = new Set<Part>()
  if (media.stale.keyframe || !media.keyframe || edited.includes("keyframe")) auto.add("keyframe")
  if (shot.lines.length && (wordsStale || status.missing.includes("voice") || edited.includes("voice"))) auto.add("voice")
  const waitsFor = useWaits(studio)
  const can = (p: Part) => (p === "keyframe" ? true : p === "voice" ? draft.lines.length > 0 : paidMode)
  const isOn = (p: Part) => can(p) && !waitsFor(p) && (picked[p] ?? auto.has(p))
  const parts = PARTS.filter(isOn)
  const tick = (p: Part) => ({ checked: isOn(p), disabled: !!waitsFor(p), onChange: (on: boolean) => setPicked((x) => ({ ...x, [p]: on })) })

  const engine = draft.motion.engine ?? flow.catalog.default_engine
  const clipPrice = paidMode ? (flow.catalog.engines?.[engine]?.usd[String(draft.motion.clip_s ?? 5)] ?? media.price) : 0
  const partCost = usePartCosts(studio)
  const cost = parts.includes("clip") ? PAID(clipPrice) : parts.includes("keyframe") ? partCost.keyframe : parts.includes("voice") ? partCost.voice : FREE()
  const limits = useContext(LimitsContext)
  const writing = blocked(useTaskCost(studio, ["revise"], "writing"), limits)
  const noted = note.trim().length > 0
  const locked = flowStep(flow, "scenes").locked
  const ready = !busy && !locked && !(noted && (!parts.length || writing))

  const label = !made
    ? "Make scene"
    : parts.length
      ? `Redo ${parts.map((p) => NAME[p]).join(" + ")}`
      : dirty
        ? "Save and update preview"
        : "Update preview"
  const hint =
    noted && !parts.length
      ? "Tick the part the note is for."
      : noted && writing
        ? `The writer's free limit is used up. It comes back ${back(writing).text}; until then edit by hand.`
        : parts.includes("keyframe") && media.clip && !parts.includes("clip")
          ? "The bought clip won't match a new still. Tick Clip to buy one that does."
          : !parts.length && untuned
            ? "Updating the preview applies the voice tuning too."
            : null

  async function redo() {
    setErrors([])
    const masked = draft.motion.mode === "masked_i2v" || draft.motion.mode === "cinemagraph"
    if (shotDirty && masked && !draft.motion.mask?.target?.trim()) {
      setErrors(["Say what should move in this scene (the box under the motion prompt)"])
      return
    }
    const sent = structuredClone(draft)
    if (!masked && !sent.motion.mask?.target?.trim()) delete sent.motion.mask
    let started: Job
    try {
      started = await api.redoScene(shot.id, {
        parts,
        shot: shotDirty ? sent : undefined,
        voices: changedVoices.length ? Object.fromEntries(changedVoices.map((id) => [id, clean(voices[id])])) : undefined,
        note: noted ? note.trim() : undefined,
        confirm_usd: parts.includes("clip") ? clipPrice : undefined,
      })
    } catch (err) {
      setErrors(err instanceof ApiError && err.errors.length ? err.errors : [(err as Error).message])
      return
    }
    const job = await studio.finish(Promise.resolve(started))
    if (job?.status !== "done") return
    resync.current = true
    setNote("")
    setPicked({})
    const changed = (job.result as { changed?: string[] } | null)?.changed ?? []
    if (changed.length) toast(`Your note rewrote the ${changed.join(" and ")}`)
  }

  function discard() {
    setDraft(shot)
    setVoices(savedVoices)
    setNote("")
    setPicked({})
    setErrors([])
  }

  const n = sb.shots.findIndex((s) => s.id === shot.id) + 1
  const keyframeStatus: [Tone, string] | null = media.stale.keyframe ? ["stale", "Out of date"] : !media.keyframe ? ["missing", "Not drawn"] : null
  const voiceStatus: [Tone, string] | null = wordsStale
    ? ["stale", "Out of date"]
    : status.missing.includes("voice")
      ? ["missing", "Not recorded"]
      : untuned
        ? ["stale", "Tuning not applied"]
        : null
  const clipStatus: [Tone, string] = !paidMode
    ? ["ok", "Free, made in the preview"]
    : media.stale.clip
      ? ["stale", "Out of date"]
      : media.clip && draft.motion.mode === shot.motion.mode
        ? ["ok", "Bought"]
        : ["paid", `${usd(clipPrice)} to buy`]

  return (
    <>
      <section aria-label={`${shot.id} picture`} className="relative flex min-w-0 flex-1 items-center justify-center bg-muted/40 px-16 py-6">
        <Stage studio={studio} shot={shot} media={media} />
        <Button
          variant="outline"
          size="icon"
          className="absolute top-1/2 left-4 -translate-y-1/2 rounded-full"
          disabled={!prev}
          onClick={() => prev && onScene(prev)}
          aria-label="Previous scene"
          title={prev && `Previous: ${prev} (←)`}
        >
          <ChevronLeft />
        </Button>
        <Button
          variant="outline"
          size="icon"
          className="absolute top-1/2 right-4 -translate-y-1/2 rounded-full"
          disabled={!next}
          onClick={() => next && onScene(next)}
          aria-label="Next scene"
          title={next && `Next: ${next} (→)`}
        >
          <ChevronRight />
        </Button>
      </section>

      <aside aria-label={`${shot.id} settings`} className="flex w-[420px] shrink-0 flex-col border-l">
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-6">
          <header className="mb-4">
            <h2 className="text-xl font-semibold tracking-tight">Scene {n}</h2>
            <div className="text-[12px] text-subtle tabular-nums">
              {shot.id} · {shot.size} · {shot.duration_s} s · {n} of {sb.shots.length}
            </div>
          </header>
          <ApproveBar studio={studio} step="scenes" scene={shot.id} what={shot.id} />
          {flowScene && flowScene.history.length > 1 && <Versions studio={studio} id={shot.id} history={flowScene.history} />}
          <p className="text-[13px] text-muted-foreground">
            <span className="font-medium text-foreground">{shot.beat}</span>
            {shot.reason && <span className="text-subtle"> {shot.reason}</span>}
          </p>

          <div className="mt-5 divide-y border-y">
            <PartSection
              title={draft.motion.mode === "flf_inbetween" ? "Still and end frame" : "Still"}
              tick={tick("keyframe")}
              status={keyframeStatus}
              edited={edited.includes("keyframe")}
              waits={waitsFor("keyframe")}
              picker={<TaskPicker studio={studio} task="image" />}
            >
              <Textarea
                value={draft.keyframe.prompt}
                onChange={(e) => set((s) => void (s.keyframe.prompt = e.target.value))}
                aria-label="What the still shows"
                className="min-h-20 text-[13px]"
              />
              {draft.motion.mode === "flf_inbetween" && (
                <Textarea
                  value={draft.motion.end_keyframe?.prompt ?? ""}
                  onChange={(e) => set((s) => void (s.motion.end_keyframe = { ...s.motion.end_keyframe!, prompt: e.target.value }))}
                  placeholder="Same place and camera: the end state"
                  aria-label="The end frame"
                  className="min-h-14 text-[13px]"
                />
              )}
            </PartSection>

            {draft.lines.length > 0 && (
              <PartSection
                title={draft.lines.length > 1 ? `Voice · ${draft.lines.length} lines` : "Voice"}
                tick={tick("voice")}
                status={voiceStatus}
                edited={edited.includes("voice") || tuneEdited}
                waits={waitsFor("voice")}
                picker={<TaskPicker studio={studio} task="tts" />}
              >
                <VoiceLines
                  shot={shot}
                  draft={draft}
                  media={media}
                  cast={cast}
                  voices={voices}
                  savedVoices={savedVoices}
                  others={(cid) => sb.shots.filter((s) => s.id !== shot.id).flatMap((s) => s.lines).filter((l) => l.speaker === cid && !l.tune).length}
                  onLines={(fn) => set((s) => fn(s.lines))}
                  onVoice={(cid, t) => setVoices((v) => ({ ...v, [cid]: t }))}
                />
              </PartSection>
            )}

            <PartSection
              title="Motion"
              tick={paidMode ? tick("clip") : undefined}
              tickLabel="clip"
              status={clipStatus}
              edited={JSON.stringify(shot.motion) !== JSON.stringify(draft.motion)}
              picker={
                <>
                  {paidMode && <TaskPicker studio={studio} task="video" />}
                  {(draft.motion.mode === "masked_i2v" || draft.motion.mode === "cinemagraph") && <TaskPicker studio={studio} task="mask" label="Mask" />}
                </>
              }
            >
              <MotionEditor draft={draft} set={set} />
              {media.used && media.used !== shot.motion.mode && (
                <p className="text-[12px] text-warn">The last cut used {MODES[media.used]?.label ?? media.used} instead.</p>
              )}
            </PartSection>
          </div>
        </div>

        <footer className="shrink-0 space-y-2.5 border-t bg-background px-6 pt-3 pb-4">
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && ready && !parts.includes("clip") && redo()}
            placeholder="A note for the redo (optional): Grandma laughing, warmer light, a softer line…"
            aria-label="A note for the redo"
            className="min-h-14 resize-none text-[13px]"
          />
          {noted && <TaskPicker studio={studio} task="revise" label="Writer" />}
          {errors.length > 0 && (
            <ul className="space-y-1 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive">
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          <div className="flex items-center gap-2">
            <RunButton
              cost={cost}
              className={parts.includes("clip") ? "border-paid/40 text-paid hover:bg-paid/10 hover:text-paid" : undefined}
              spent={studio.state.spent}
              what={`One ${draft.motion.clip_s ?? 5} s clip of ${shot.id}.`}
              confirm={parts.includes("clip") ? { title: "", body: null, action: "Buy clip" } : undefined}
              disabled={!ready}
              onRun={redo}
            >
              {label}
            </RunButton>
            {(dirty || noted) && (
              <Button variant="ghost" onClick={discard} disabled={busy}>
                Discard
              </Button>
            )}
          </div>
          {hint && <p className="text-[12px] text-subtle">{hint}</p>}
        </footer>
      </aside>
    </>
  )
}

/** One part of the scene: a tick to redo it, its state and model, and its fields. */
function PartSection({
  title,
  tick,
  tickLabel,
  status,
  edited,
  waits,
  picker,
  children,
}: {
  title: string
  tick?: { checked: boolean; disabled: boolean; onChange: (on: boolean) => void }
  /** What the tick redoes, when it is not the title (Motion buys a clip). */
  tickLabel?: string
  status: [Tone, string] | null
  edited?: boolean
  waits?: ReturnType<typeof blocked>
  picker?: React.ReactNode
  children: React.ReactNode
}) {
  const what = `Redo the ${tickLabel ?? title.toLowerCase()}`
  return (
    <section className="space-y-2.5 py-4">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {tick && <Checkbox checked={tick.checked} disabled={tick.disabled} onCheckedChange={(on) => tick.onChange(!!on)} aria-label={what} title={what} />}
        <h3 className="text-[13px] font-semibold">{title}</h3>
        {waits ? (
          <StatusDot status="stale">Free limit used up, back {back(waits).time}</StatusDot>
        ) : edited ? (
          <span className="text-[12px] text-primary">Edited</span>
        ) : (
          status && <StatusDot status={status[0]}>{status[1]}</StatusDot>
        )}
        <span className="ml-auto flex items-center gap-2">{picker}</span>
      </div>
      {children}
    </section>
  )
}

/** The big picture in the middle: the made preview, the still, the end frame or the clip. */
function Stage({ studio, shot, media }: { studio: Studio; shot: Shot; media: ShotState }) {
  const made = studio.flow.scenes.find((s) => s.id === shot.id)?.preview ?? null
  const views = [
    ...(made ? [{ id: "preview", label: "Preview", url: made, stale: false }] : []),
    {
      id: "still",
      label: "Still",
      url: media.keyframe,
      stale: media.stale.keyframe,
    },
    ...(media.end
      ? [
          {
            id: "end",
            label: "End frame",
            url: media.end,
            stale: media.stale.keyframe,
          },
        ]
      : []),
    ...(media.paid
      ? [
          {
            id: "clip",
            label: "Clip",
            url: media.clip,
            stale: media.stale.clip,
          },
        ]
      : []),
  ]
  const [view, setView] = useState(made ? "preview" : media.clip ? "clip" : "still")
  const current = views.find((v) => v.id === view) ?? views[0]

  return (
    <div className="flex h-full min-h-0 w-full flex-col items-center gap-3">
      {views.length > 1 && (
        <ToggleGroup
          value={[current.id]}
          onValueChange={(v) => v[0] && setView(v[0])}
          size="sm"
          variant="outline"
          spacing={0}
          className="shrink-0 bg-background"
        >
          {views.map((v) => (
            <ToggleGroupItem key={v.id} value={v.id} className="px-3">
              {v.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      )}
      <div className="flex min-h-0 w-full flex-1 items-center justify-center">
        <div className="relative aspect-[9/16] h-full max-h-full max-w-full overflow-hidden rounded-lg bg-secondary shadow-lg ring-1 ring-border">
          {current.url && current.id === "preview" && <video key={current.url} src={current.url} className="size-full object-cover" controls playsInline />}
          {current.url && current.id !== "clip" && current.id !== "preview" && <img src={current.url} alt={current.label} className="size-full object-cover" />}
          {current.url && current.id === "clip" && (
            <video key={current.url} src={current.url} className="size-full object-cover" autoPlay loop muted playsInline />
          )}
          {!current.url && (
            <div className="grid size-full place-items-center px-6 text-center text-[12.5px] text-subtle">
              {current.id === "clip" ? "No clip bought yet. The film uses free motion here until you buy one." : "Not drawn yet"}
            </div>
          )}
          {current.url && current.stale && (
            <span className="absolute top-2 left-2 rounded-[4px] bg-black/70 px-1.5 py-0.5 text-[11px] font-medium text-warn backdrop-blur">Out of date</span>
          )}
        </div>
      </div>
    </div>
  )
}

function MotionEditor({ draft, set }: { draft: Shot; set: Draft }) {
  const mode = draft.motion.mode
  const flow = useContext(FlowContext)
  const allowed = flow?.budget?.allowed_modes ?? Object.keys(MODES)
  const items = Object.entries(flow?.catalog.modes ?? MODES).map(([value, m]) => ({
    value,
    label: m.label,
    paid: m.paid,
    usd: "usd" in m ? (m.usd as number) : 0,
    allowed: allowed.includes(value),
  }))
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          items={items}
          value={mode}
          onValueChange={(value) =>
            set((s) => {
              s.motion.mode = String(value)
              if ((value === "masked_i2v" || value === "cinemagraph") && !s.motion.mask) s.motion.mask = { target: "" }
              if (value !== "masked_i2v" && value !== "cinemagraph" && !s.motion.mask?.target?.trim()) delete s.motion.mask
              if (value === "flf_inbetween" && !s.motion.end_keyframe)
                s.motion.end_keyframe = {
                  prompt: "Same place and camera: ",
                  seed: s.keyframe.seed + 1,
                }
              if (value === "parallax" && !s.motion.parallax) s.motion.parallax = { move: "push-in", amount: 0.03 }
            })
          }
        >
          <SelectTrigger className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {items.map((i) => (
              <SelectItem key={i.value} value={i.value} disabled={!i.allowed}>
                {i.label}
                <span className={cn("ml-auto pl-3 text-[11px] tabular-nums", !i.allowed ? "text-subtle" : i.paid ? "text-paid" : "text-free")}>
                  {!i.allowed ? "not allowed" : i.paid ? usd(i.usd) : "free"}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {MODES[mode]?.paid && (
          <ToggleGroup
            value={[String(draft.motion.clip_s ?? 5)]}
            onValueChange={(v) => v[0] && set((s) => void (s.motion.clip_s = Number(v[0])))}
            variant="outline"
            size="sm"
            spacing={0}
          >
            {[5, 8].map((n) => (
              <ToggleGroupItem key={n} value={String(n)}>
                {n} s clip
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </div>
      <Textarea
        value={draft.motion.prompt}
        onChange={(e) => set((s) => void (s.motion.prompt = e.target.value))}
        placeholder="Only the motion and the camera"
        className="min-h-14 text-[13px]"
      />
      {(mode === "masked_i2v" || mode === "cinemagraph") && (
        <Input
          value={draft.motion.mask?.target ?? ""}
          onChange={(e) =>
            set(
              (s) =>
                void (s.motion.mask = {
                  ...s.motion.mask,
                  target: e.target.value,
                  regions: undefined,
                }),
            )
          }
          placeholder="What should move, in words (e.g. the steam above the cups)"
        />
      )}
      {mode === "flf_inbetween" && (
        <Textarea
          value={draft.motion.end_keyframe?.prompt ?? ""}
          onChange={(e) =>
            set(
              (s) =>
                void (s.motion.end_keyframe = {
                  ...s.motion.end_keyframe!,
                  prompt: e.target.value,
                }),
            )
          }
          placeholder="Same place and camera: the end state"
          className="min-h-14 text-[13px]"
        />
      )}
      {mode === "parallax" && (
        <Choices
          value={draft.motion.parallax?.move ?? "push-in"}
          options={["push-in", "pull-out", "slide-left", "slide-right", "rise"]}
          onChange={(move) => set((s) => void (s.motion.parallax = { ...s.motion.parallax, move }))}
        />
      )}
      {mode === "still_kenburns" && (
        <Choices
          value={draft.motion.kenburns ?? "zoom-in"}
          options={["zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down"]}
          onChange={(k) => set((s) => void (s.motion.kenburns = k))}
        />
      )}
    </div>
  )
}

function Choices({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <ToggleGroup value={[value]} onValueChange={(v) => v[0] && onChange(v[0])} variant="outline" size="sm" className="flex-wrap">
      {options.map((o) => (
        <ToggleGroupItem key={o} value={o}>
          {o.replace("-", " ")}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

/** Which motion modes scenes may use, and what the whole film may spend on clips. */
export function BudgetButton({ studio }: { studio: Studio }) {
  const { flow, refresh } = studio
  const b = flow.budget
  const [open, setOpen] = useState(false)
  const [modes, setModes] = useState<string[]>(b?.allowed_modes ?? [])
  const [budget, setBudget] = useState(String(b?.budget_usd ?? 0.6))
  useEffect(() => {
    if (!open || !b) return
    setModes(b.allowed_modes)
    setBudget(String(b.budget_usd))
  }, [open, b])
  if (!b) return null

  async function save() {
    try {
      await api.setVideo({ allowed_modes: modes, budget_usd: Number(budget) })
      toast.success("Modes and budget saved")
      setOpen(false)
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const over = b.planned_usd > b.budget_usd
  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        title={`${b.allowed_modes.length} of ${Object.keys(flow.catalog.modes).length} motion modes allowed`}
      >
        Modes and budget
        <span className={cn("tabular-nums", over ? "text-warn" : "text-muted-foreground")}>
          {usd(b.planned_usd)} planned of {usd(b.budget_usd)}
        </span>
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Motion modes and budget</DialogTitle>
            <DialogDescription>Each scene can only pick an allowed mode, and the paid ones together must fit the budget.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            {Object.entries(flow.catalog.modes).map(([id, m]) => (
              <label key={id} className="flex items-center gap-2.5 rounded-md px-1 py-1 text-[13px] hover:bg-muted/60">
                <Checkbox checked={modes.includes(id)} onCheckedChange={(on) => setModes(on ? [...modes, id] : modes.filter((x) => x !== id))} />
                <span className="flex-1">{m.label}</span>
                <span className={cn("text-[12px] tabular-nums", m.paid ? "text-paid" : "text-free")}>{m.paid ? `${usd(m.usd)} a clip` : "free"}</span>
              </label>
            ))}
          </div>
          <label className="mt-2 flex items-center gap-3 text-[13px]">
            <span className="flex-1">Most the film may spend on clips</span>
            <span className="text-subtle">$</span>
            <Input type="number" min={0} max={10} step={0.05} value={budget} onChange={(e) => setBudget(e.target.value)} className="w-24" />
          </label>
          <p className="text-[12px] text-subtle">
            The scenes' chosen modes add up to {usd(b.planned_usd)}; {usd(b.to_buy_usd)} of that is not bought yet.
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={!modes.length}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** Earlier approved versions of a scene. Putting one back costs nothing: its files are still cached. */
function Versions({ studio, id, history }: { studio: Studio; id: string; history: Flow["scenes"][number]["history"] }) {
  async function restore(i: number) {
    try {
      await api.restoreScene(id, i)
      toast.success(`${id}: version ${i + 1} is back`)
      await studio.refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }
  return (
    <div className="-mt-3 mb-6 flex flex-wrap items-center gap-1.5 text-[12px]">
      <span className="mr-1 text-subtle">Approved versions</span>
      {history.map((v, i) => (
        <Button
          key={v.hash}
          size="xs"
          variant="outline"
          disabled={studio.busy}
          onClick={() => restore(i)}
          title={`Approved ${new Date(v.at).toLocaleString()}`}
        >
          v{i + 1} · {MODES[v.mode]?.label ?? v.mode}
        </Button>
      ))}
    </div>
  )
}

/** What redoing a scene's still or voice costs, from the Pictures and Voices pickers. */
function usePartCosts(studio: Studio): Record<"keyframe" | "voice", Cost> {
  return useTaskCosts(studio, {
    keyframe: [["image"], "pictures"],
    voice: [["tts"], "voices"],
  })
}

/** The used-up free limit a part waits for, if the model picked for it can run nowhere else. */
function useWaits(studio: Studio) {
  const limits = useContext(LimitsContext)
  const costs = usePartCosts(studio)
  return (p: Part) => (p === "clip" ? null : blocked(costs[p], limits))
}

/** A scene's band colour: green approved, red changed or out of date, gold ready to approve, bare thread when not made. */
export function toneOf(f: Flow["scenes"][number] | undefined, status: ReturnType<typeof scene>) {
  if (f?.state === "approved") return "weave-done"
  if (f?.state === "stale" || status.stale.length) return "weave-stale"
  if (f && !f.blockers.length) return "weave-current"
  return "weave-locked"
}

const TONE_WORD: Record<string, string> = {
  "weave-done": "approved",
  "weave-stale": "needs you",
  "weave-current": "ready to approve",
  "weave-locked": "not made yet",
}
