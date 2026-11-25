import { ArrowRight, Check, ChevronDown, ChevronUp, Sparkles, X } from "lucide-react"
import { useContext, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { ApiError, api, diff, MODES, type Shot, type ShotState } from "@/api"
import type { Studio } from "@/App"
import { CostTag, RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { LimitsContext } from "@/lib/limits"
import { affected, back, blocked, FREE, fieldLabel, LIMIT_OF, PAID, PART_LABEL, scene, usd, type Part } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { StatusDot } from "@/views/parts"

export function ScenesView({ studio, onScene }: { studio: Studio; onScene: (id: string) => void }) {
  const sb = studio.state.storyboard
  if (!sb) return <div className="p-10 text-muted-foreground">Draft the scenes from your story first.</div>
  const shot = sb.shots.find((s) => s.id === studio.scene) ?? sb.shots[0]
  const media = studio.state.shots.find((s) => s.id === shot.id)!
  const i = sb.shots.indexOf(shot)
  return (
    <div className="grid min-h-full grid-cols-[272px_minmax(0,1fr)]">
      <SceneList studio={studio} selected={shot.id} onSelect={onScene} />
      <SceneWorkspace
        key={shot.id}
        studio={studio}
        shot={shot}
        media={media}
        prev={sb.shots[i - 1]?.id}
        next={sb.shots[i + 1]?.id}
        onScene={onScene}
      />
    </div>
  )
}

function SceneList({ studio, selected, onSelect }: { studio: Studio; selected: string; onSelect: (id: string) => void }) {
  const sb = studio.state.storyboard!
  const [filter, setFilter] = useState<"all" | "work">("all")
  const rows = sb.shots.map((s) => {
    const m = studio.state.shots.find((x) => x.id === s.id)!
    return { s, m, status: scene(m) }
  })
  const work = rows.filter((r) => r.status.needsWork).length
  const toBuy = rows.filter((r) => r.status.toBuy)
  const shown = filter === "work" ? rows.filter((r) => r.status.needsWork) : rows
  return (
    <nav className="sticky top-0 flex h-screen flex-col border-r">
      <div className="border-b px-4 pt-8 pb-3">
        <div className="text-[12px] text-subtle">Step 3 of 4</div>
        <h1 className="text-lg font-semibold tracking-tight">Scenes</h1>
        <p className="mt-0.5 text-[12px] text-subtle">
          {sb.shots.length} scenes · {toBuy.length ? `${toBuy.length} clips to buy (${usd(toBuy.reduce((n, r) => n + r.m.price, 0))})` : "all clips bought"}
        </p>
        <ToggleGroup
          value={[filter]}
          onValueChange={(v) => v[0] && setFilter(v[0] as "all" | "work")}
          variant="outline"
          size="sm"
          spacing={0}
          className="mt-3 w-full"
        >
          <ToggleGroupItem value="all" className="flex-1">
            All
          </ToggleGroupItem>
          <ToggleGroupItem value="work" className="flex-1">
            Needs redo <span className={cn("tabular-nums", work ? "text-warn" : "text-subtle")}>{work}</span>
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {shown.length === 0 && <p className="p-3 text-[12.5px] text-subtle">Nothing needs a redo.</p>}
        {shown.map(({ s, m, status }) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn("flex w-full items-start gap-3 rounded-md p-2 text-left transition-colors hover:bg-muted/70", selected === s.id && "bg-muted")}
          >
            <div className="aspect-[9/16] w-10 shrink-0 overflow-hidden rounded-[4px] bg-secondary ring-1 ring-border">
              {m.keyframe && <img src={m.keyframe} alt="" className={cn("size-full object-cover", status.stale.includes("keyframe") && "opacity-60")} />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] font-semibold">{s.id}</span>
                <span className={cn("text-[11.5px]", MODES[s.motion.mode]?.paid ? "text-paid" : "text-subtle")}>{MODES[s.motion.mode]?.label ?? s.motion.mode}</span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-muted-foreground">{s.lines[0]?.en ?? s.beat}</p>
              {status.stale.length > 0 && (
                <StatusDot status="stale" className="mt-1 text-[11.5px]">
                  {status.stale.map((p) => PART_LABEL[p]).join(", ")} out of date
                </StatusDot>
              )}
              {status.stale.length === 0 && status.missing.length > 0 && (
                <StatusDot status="missing" className="mt-1 text-[11.5px]">
                  {status.missing.map((p) => PART_LABEL[p]).join(", ")} not made
                </StatusDot>
              )}
            </div>
          </button>
        ))}
      </div>
    </nav>
  )
}

type Draft = (fn: (s: Shot) => void) => void

function SceneWorkspace({
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
  const { refresh, track, busy } = studio
  const [draft, setDraft] = useState<Shot>(shot)
  const [errors, setErrors] = useState<string[]>([])
  const [tab, setTab] = useState<"feedback" | "edit">("feedback")
  const dirty = JSON.stringify(draft) !== JSON.stringify(shot)
  useEffect(() => {
    if (!dirty) setDraft(shot)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shot])

  const set: Draft = (fn) =>
    setDraft((p) => {
      const n = structuredClone(p)
      fn(n)
      return n
    })

  async function save(nextShot: Shot = draft) {
    try {
      await api.saveShot(nextShot)
      setErrors([])
      const parts = affected(shot, nextShot, !!media.clip)
      toast.success(parts.length ? `${shot.id} saved. Redo ${parts.map((p) => PART_LABEL[p].toLowerCase()).join(" and ")} to see it.` : `${shot.id} saved`)
      await refresh()
      return true
    } catch (err) {
      setErrors(err instanceof ApiError && err.errors.length ? err.errors : [(err as Error).message])
      return false
    }
  }

  const status = scene(media)
  return (
    <div className="min-w-0 px-10 pt-8 pb-28">
      <header className="mb-6 flex items-start gap-6">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[12px] text-subtle">
            {shot.id} · {shot.size} · {shot.duration_s} s
          </div>
          <h2 className="mt-0.5 text-xl font-semibold tracking-tight">{shot.beat}</h2>
          <p className="mt-1 max-w-3xl text-muted-foreground">{shot.reason}</p>
        </div>
        <div className="flex gap-1">
          <Button variant="outline" size="icon-sm" disabled={!prev} onClick={() => prev && onScene(prev)} aria-label="Previous scene">
            <ChevronUp />
          </Button>
          <Button variant="outline" size="icon-sm" disabled={!next} onClick={() => next && onScene(next)} aria-label="Next scene">
            <ChevronDown />
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-[280px_minmax(0,1fr)] gap-10">
        <Preview studio={studio} shot={shot} media={media} />

        <div className="min-w-0">
          <Tabs value={tab} onValueChange={(v) => setTab(v as "feedback" | "edit")}>
            <TabsList variant="line" className="mb-4 h-auto border-b pb-0 w-full justify-start rounded-none">
              <TabsTrigger value="feedback" className="flex-none px-1 pb-2.5">
                <Sparkles /> Give feedback
              </TabsTrigger>
              <TabsTrigger value="edit" className="ml-4 flex-none px-1 pb-2.5">
                Edit by hand {dirty && <span className="size-1.5 rounded-full bg-primary" />}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="feedback" keepMounted>
              <FeedbackPanel
                shot={shot}
                hasClip={!!media.clip}
                dirty={dirty}
                busy={busy}
                onEdit={() => setTab("edit")}
                onKeys={() => studio.go("keys")}
                onAccept={async (proposal, redo) => {
                  if (!(await save(proposal))) return false
                  if (redo.length) await track(api.redo(shot.id, redo))
                  return true
                }}
              />
            </TabsContent>
            <TabsContent value="edit" keepMounted>
              <EditPanel shot={shot} draft={draft} set={set} />
              {errors.length > 0 && (
                <ul className="mt-4 space-y-1 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-[13px] text-destructive">
                  {errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              )}
              <div className="sticky bottom-0 z-10 mt-5 flex items-center gap-2 border-t bg-background/95 py-3 backdrop-blur">
                <Button onClick={() => save()} disabled={!dirty}>
                  Save scene
                </Button>
                <Button variant="ghost" onClick={() => (setDraft(shot), setErrors([]))} disabled={!dirty}>
                  Discard
                </Button>
                {dirty && <WillMakeStale parts={affected(shot, draft, !!media.clip)} prefix="Saving puts" />}
              </div>
            </TabsContent>
          </Tabs>

          <RedoPanel
            key={JSON.stringify([media.stale, status.missing])}
            studio={studio}
            shot={shot}
            media={media}
            disabled={busy || dirty}
            onRedo={(parts) => track(api.redo(shot.id, parts))}
          />
        </div>
      </div>
    </div>
  )
}

function WillMakeStale({ parts, prefix }: { parts: Part[]; prefix: string }) {
  if (!parts.length) return <span className="text-[12px] text-subtle">Nothing needs a redo after this (subtitles and notes only).</span>
  return (
    <span className="text-[12px] text-muted-foreground">
      {prefix} <span className="text-warn">{parts.map((p) => PART_LABEL[p].toLowerCase()).join(", ")}</span> out of date.
    </span>
  )
}

function Preview({ studio, shot, media }: { studio: Studio; shot: Shot; media: ShotState }) {
  const names = useMemo(() => Object.fromEntries(studio.state.storyboard!.characters.map((c) => [c.id, c.name])), [studio.state.storyboard])
  const views = [
    { id: "still", label: "Still", url: media.keyframe, stale: media.stale.keyframe },
    ...(media.end ? [{ id: "end", label: "End frame", url: media.end, stale: media.stale.keyframe }] : []),
    ...(media.paid ? [{ id: "clip", label: "Clip", url: media.clip, stale: media.stale.clip }] : []),
  ]
  const [view, setView] = useState(media.clip ? "clip" : "still")
  const current = views.find((v) => v.id === view) ?? views[0]
  const mode = MODES[shot.motion.mode] ?? { label: shot.motion.mode, paid: false }

  return (
    <div className="sticky top-6 self-start">
      {views.length > 1 && (
        <ToggleGroup value={[current.id]} onValueChange={(v) => v[0] && setView(v[0])} size="sm" variant="outline" spacing={0} className="mb-2 w-full">
          {views.map((v) => (
            <ToggleGroupItem key={v.id} value={v.id} className="flex-1">
              {v.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      )}
      <div className="relative aspect-[9/16] overflow-hidden rounded-lg bg-secondary ring-1 ring-border">
        {current.url && current.id !== "clip" && <img src={current.url} alt={current.label} className="size-full object-cover" />}
        {current.url && current.id === "clip" && <video src={current.url} className="size-full object-cover" autoPlay loop muted playsInline />}
        {!current.url && (
          <div className="grid size-full place-items-center px-6 text-center text-[12.5px] text-subtle">
            {current.id === "clip" ? "No clip bought yet. The film uses free motion here until you buy one." : "Not drawn yet"}
          </div>
        )}
        {current.url && current.stale && (
          <span className="absolute top-2 left-2 rounded-[4px] bg-black/70 px-1.5 py-0.5 text-[11px] font-medium text-warn backdrop-blur">
            Out of date
          </span>
        )}
      </div>
      <div className="mt-2.5 flex items-center justify-between text-[12px]">
        <span className={mode.paid ? "text-paid" : "text-subtle"}>{mode.label}</span>
        <span className="text-subtle">
          {mode.paid ? (media.clip ? "clip bought" : `clip ${usd(media.price)} to buy`) : "free, made in the cut"}
        </span>
      </div>
      {media.used && media.used !== shot.motion.mode && (
        <p className="mt-1 text-[12px] text-warn">The last cut used {MODES[media.used]?.label ?? media.used} instead.</p>
      )}

      {shot.lines.length > 0 && (
        <div className="mt-5 space-y-3 border-t pt-4">
          {shot.lines.map((line, i) => {
            const take = media.lines[i]
            const heard = take?.cer != null ? Math.round((1 - Math.min(1, take.cer)) * 100) : null
            return (
              <div key={i}>
                <div className="mb-1 flex items-center gap-2 text-[12px]">
                  <span className="font-medium">{names[line.speaker] ?? line.speaker}</span>
                  {take?.seconds != null && <span className="text-subtle tabular-nums">{take.seconds.toFixed(1)} s</span>}
                  {media.stale.voice[i] ? (
                    <StatusDot status="stale" className="ml-auto text-[11.5px]">
                      Out of date
                    </StatusDot>
                  ) : (
                    heard != null && (
                      <span className={cn("ml-auto tabular-nums", heard < 65 ? "text-warn" : "text-subtle")} title={`Heard back: ${take?.heard ?? ""}`}>
                        {heard}% heard back
                      </span>
                    )
                  )}
                </div>
                <p lang="am" className="text-[13.5px] leading-snug">
                  {line.text}
                </p>
                <p className="text-[12px] text-subtle">{line.en}</p>
                {take?.audio ? <audio controls src={take.audio} className="mt-1.5 h-8 w-full" /> : <p className="mt-1 text-[12px] text-subtle">Not recorded yet</p>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function FeedbackPanel({
  shot,
  hasClip,
  dirty,
  busy,
  onEdit,
  onKeys,
  onAccept,
}: {
  shot: Shot
  hasClip: boolean
  dirty: boolean
  busy: boolean
  onEdit: () => void
  onKeys: () => void
  onAccept: (s: Shot, redo: Part[]) => Promise<boolean>
}) {
  const [text, setText] = useState("")
  const [loading, setLoading] = useState(false)
  const [proposal, setProposal] = useState<{ shot: Shot; errors: string[] } | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const changes = proposal ? diff(shot, proposal.shot) : []
  const parts = proposal ? affected(shot, proposal.shot, hasClip) : []
  const limits = useContext(LimitsContext)
  const writing = blocked(FREE("Gemini", "writing"), limits)
  const waitsFor = (p: Part) => blocked(FREE(undefined, LIMIT_OF[p]), limits)
  const free = parts.filter((p) => p !== "clip" && !waitsFor(p))
  const waiting = parts.filter((p) => p !== "clip" && waitsFor(p))

  async function ask() {
    setLoading(true)
    setFailed(null)
    try {
      const res = await api.feedback(shot.id, text)
      setProposal({ shot: res.proposal, errors: res.errors })
    } catch (err) {
      const message = (err as Error).message
      setFailed(
        /quota/i.test(message)
          ? `Gemini's free writing limit is used up for today.${limits?.writing ? ` It comes back ${back(limits.writing).text}.` : ""} Until then you can edit the scene by hand.`
          : message,
      )
    } finally {
      setLoading(false)
    }
  }

  async function accept(redo: Part[]) {
    if (await onAccept(proposal!.shot, redo)) {
      setProposal(null)
      setText("")
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim() && !dirty && !writing && ask()}
          placeholder="What should change? For example: Grandma should be laughing, and the line should mention Sunday."
          className="min-h-24 text-[13px]"
        />
        <div className="mt-2 flex items-center gap-3">
          <Button onClick={ask} disabled={!text.trim() || loading || dirty || !!writing}>
            <Sparkles /> {loading ? "Gemini is revising…" : "Revise with Gemini"}
            <CostTag cost={FREE("Gemini", "writing")} className={cn("-mr-1", !writing && "bg-white/15 text-white")} />
          </Button>
          {writing ? null : dirty ? (
            <span className="text-[12px] text-subtle">
              You have unsaved hand edits.{" "}
              <button className="text-foreground underline-offset-2 hover:underline" onClick={onEdit}>
                Save or discard them
              </button>{" "}
              first.
            </span>
          ) : (
            <span className="text-[12px] text-subtle">Nothing changes until you accept.</span>
          )}
        </div>
        {writing && (
          <p className="mt-2 text-[12px] text-warn">
            Today's free Gemini writing is used up. It comes back {back(writing).text}.{" "}
            <button className="text-foreground underline-offset-2 hover:underline" onClick={onKeys}>
              Add a key
            </button>{" "}
            from another Google project to go on now, or{" "}
            <button className="text-foreground underline-offset-2 hover:underline" onClick={onEdit}>
              edit by hand
            </button>
            .
          </p>
        )}
      </div>

      {failed && !proposal && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/8 px-3 py-2 text-[12.5px] text-destructive">
          {failed}{" "}
          {/quota/.test(failed) && (
            <button className="text-foreground underline-offset-2 hover:underline" onClick={onEdit}>
              Edit by hand
            </button>
          )}
        </p>
      )}
      {proposal && (
        <div className="rounded-lg border bg-card">
          <div className="flex items-center justify-between border-b px-4 py-2.5">
            <span className="text-[13px] font-medium">Gemini's revision</span>
            <span className="text-[12px] text-subtle">
              {changes.length} change{changes.length === 1 ? "" : "s"}
            </span>
          </div>
          <div className="divide-y">
            {changes.length === 0 && <p className="px-4 py-3 text-[13px] text-muted-foreground">Gemini proposed no change. Try saying it differently.</p>}
            {changes.map((c) => (
              <div key={c.path} className="grid grid-cols-[120px_minmax(0,1fr)] gap-4 px-4 py-3 text-[13px]">
                <div className="text-[12px] text-subtle">{fieldLabel(c.path)}</div>
                <div className="space-y-1">
                  <div className="text-muted-foreground line-through decoration-destructive/50">{c.before}</div>
                  <div className="text-foreground">{c.after}</div>
                </div>
              </div>
            ))}
          </div>
          {proposal.errors.length > 0 && (
            <ul className="border-t px-4 py-3 text-[12.5px] text-destructive">
              {proposal.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-2 border-t bg-muted/30 px-4 py-3">
            {free.length > 0 ? (
              <>
                <Button disabled={proposal.errors.length > 0 || busy} onClick={() => accept(free)}>
                  <Check /> Accept and redo {free.map((p) => PART_LABEL[p].toLowerCase()).join(" + ")}
                  <CostTag cost={FREE()} className="-mr-1 bg-white/15 text-white" />
                </Button>
                <Button variant="secondary" disabled={proposal.errors.length > 0} onClick={() => accept([])}>
                  Accept only
                </Button>
              </>
            ) : (
              <Button disabled={proposal.errors.length > 0 || changes.length === 0} onClick={() => accept([])}>
                <Check /> Accept
              </Button>
            )}
            <Button variant="ghost" onClick={() => setProposal(null)}>
              <X /> Discard
            </Button>
            {waiting.length > 0 && (
              <span className="ml-auto text-[12px] text-warn">
                {waiting.map((p) => PART_LABEL[p]).join(" and ")} can be redone {back(waitsFor(waiting[0])!).text}, when its free limit is back.
              </span>
            )}
            {parts.includes("clip") && !waiting.length && (
              <span className="ml-auto text-[12px] text-muted-foreground">
                The clip then needs a redo too. That one is <span className="text-paid">paid</span>, below.
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function RedoPanel({
  studio,
  shot,
  media,
  disabled,
  onRedo,
}: {
  studio: Studio
  shot: Shot
  media: ShotState
  disabled: boolean
  onRedo: (parts: Part[]) => void
}) {
  const status = scene(media)
  const limits = useContext(LimitsContext)
  const waitsFor = (p: Part) => blocked(FREE(undefined, LIMIT_OF[p]), limits)
  const flf = shot.motion.mode === "flf_inbetween"
  const options: { id: Part; label: string; state: string; tone: "ok" | "stale" | "missing" | "paid"; off?: string }[] = [
    {
      id: "keyframe",
      label: flf ? "Still and end frame" : "Still",
      ...(media.stale.keyframe
        ? { state: "Out of date", tone: "stale" as const }
        : !media.keyframe
          ? { state: "Not drawn", tone: "missing" as const }
          : { state: "Up to date", tone: "ok" as const }),
    },
    {
      id: "voice",
      label: shot.lines.length > 1 ? `Voice (${shot.lines.length} lines)` : "Voice",
      off: shot.lines.length ? undefined : "No spoken line",
      ...(media.stale.voice.some(Boolean)
        ? { state: "Out of date", tone: "stale" as const }
        : status.missing.includes("voice")
          ? { state: "Not recorded", tone: "missing" as const }
          : { state: "Up to date", tone: "ok" as const }),
    },
    {
      id: "clip",
      label: "Clip",
      off: media.paid ? undefined : "Free motion, made in the cut",
      ...(media.stale.clip
        ? { state: "Out of date", tone: "stale" as const }
        : !media.clip
          ? { state: "Not bought", tone: "paid" as const }
          : { state: "Bought", tone: "ok" as const }),
    },
  ]
  const [parts, setParts] = useState<Part[]>(() =>
    options.filter((o) => !o.off && !waitsFor(o.id) && o.id !== "clip" && (o.tone === "stale" || o.tone === "missing")).map((o) => o.id),
  )
  const toggle = (p: Part, on: boolean) => setParts((x) => (on ? [...x, p] : x.filter((y) => y !== p)))
  const buying = parts.includes("clip")
  const cost = buying ? PAID(media.price) : FREE()
  const ordered = (["keyframe", "voice", "clip"] as Part[]).filter((p) => parts.includes(p))

  return (
    <section className="mt-8 border-t pt-6">
      <div className="mb-1 flex items-baseline gap-3">
        <h3 className="text-[13px] font-semibold">Redo this scene</h3>
        <span className="text-[12px] text-subtle">
          {status.stale.length
            ? `${status.stale.map((p) => PART_LABEL[p]).join(" and ")} no longer match${status.stale.length === 1 ? "es" : ""} the scene.`
            : "Everything here matches the scene."}
        </span>
      </div>
      <div className="mt-3 divide-y rounded-lg border">
        {options.map((o) => {
          const price = o.id === "clip" ? PAID(media.price) : FREE(o.id === "keyframe" ? "Cloudflare" : "Gemini", LIMIT_OF[o.id])
          const out = waitsFor(o.id)
          return (
            <label
              key={o.id}
              className={cn("flex items-center gap-3 px-3.5 py-2.5", o.off ? "opacity-50" : "cursor-pointer hover:bg-muted/40")}
            >
              <Checkbox checked={parts.includes(o.id)} disabled={!!o.off || !!out} onCheckedChange={(on) => toggle(o.id, on)} />
              <span className="w-40 text-[13px] font-medium">{o.label}</span>
              {o.off ? <span className="text-[12px] text-subtle">{o.off}</span> : <StatusDot status={o.tone}>{o.state}</StatusDot>}
              {!o.off && out && <span className="text-[12px] text-warn">· free limit used up</span>}
              {!o.off && <CostTag cost={price} className="ml-auto" />}
            </label>
          )
        })}
      </div>
      {parts.includes("keyframe") && media.paid && media.clip && !buying && (
        <p className="mt-2 text-[12px] text-muted-foreground">A new still also needs a new clip to match it. Without one, the film shows free motion here.</p>
      )}
      <div className="mt-3 flex items-center gap-3">
        <RunButton
          cost={cost}
          variant={buying ? undefined : "default"}
          className={buying ? "border-paid/40 text-paid hover:bg-paid/10 hover:text-paid" : undefined}
          spent={studio.state.spent}
          what={`One ${shot.motion.clip_s ?? 5} s clip of ${shot.id}.`}
          confirm={buying ? { title: "", body: null, action: "Buy clip" } : undefined}
          disabled={disabled || parts.length === 0}
          onRun={() => onRedo(ordered)}
        >
          {parts.length ? `Redo ${ordered.map((p) => PART_LABEL[p].toLowerCase()).join(" + ")}` : "Pick what to redo"}
        </RunButton>
        {disabled && !studio.busy && <span className="text-[12px] text-subtle">Save or discard your hand edits first.</span>}
        <button className="ml-auto inline-flex items-center gap-1 text-[12px] text-subtle hover:text-foreground" onClick={() => studio.go("film")}>
          Then see it in the film <ArrowRight className="size-3" />
        </button>
      </div>
    </section>
  )
}

function EditPanel({ shot, draft, set }: { shot: Shot; draft: Shot; set: Draft }) {
  return (
    <div className="space-y-7">
      <Field label="Lines" changed={JSON.stringify(shot.lines) !== JSON.stringify(draft.lines)}>
        {draft.lines.length === 0 && <p className="text-[13px] text-muted-foreground">No spoken line in this scene.</p>}
        <div className="space-y-3">
          {draft.lines.map((line, i) => (
            <div key={i} className="space-y-2">
              <Textarea value={line.text} lang="am" onChange={(e) => set((s) => void (s.lines[i].text = e.target.value))} className="min-h-14 text-[15px]" />
              <Input value={line.en} onChange={(e) => set((s) => void (s.lines[i].en = e.target.value))} placeholder="English subtitle" />
            </div>
          ))}
        </div>
      </Field>
      <Field label="Picture" hint="What the still shows" changed={shot.keyframe.prompt !== draft.keyframe.prompt}>
        <Textarea value={draft.keyframe.prompt} onChange={(e) => set((s) => void (s.keyframe.prompt = e.target.value))} className="min-h-24 text-[13px]" />
      </Field>
      <Field label="Motion" hint="Only the movement and the camera" changed={JSON.stringify(shot.motion) !== JSON.stringify(draft.motion)}>
        <MotionEditor draft={draft} set={set} />
      </Field>
    </div>
  )
}

function Field({ label, hint, changed, children }: { label: string; hint?: string; changed?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[13px] font-medium">{label}</span>
        {hint && <span className="text-[12px] text-subtle">{hint}</span>}
        {changed && <span className="text-[11.5px] text-primary">Edited</span>}
      </div>
      {children}
    </div>
  )
}

function MotionEditor({ draft, set }: { draft: Shot; set: Draft }) {
  const mode = draft.motion.mode
  const items = Object.entries(MODES).map(([value, m]) => ({ value, label: m.label, paid: m.paid }))
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
              if (value === "flf_inbetween" && !s.motion.end_keyframe) s.motion.end_keyframe = { prompt: "Same place and camera: ", seed: s.keyframe.seed + 1 }
              if (value === "parallax" && !s.motion.parallax) s.motion.parallax = { move: "push-in", amount: 0.03 }
            })
          }
        >
          <SelectTrigger className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {items.map((i) => (
              <SelectItem key={i.value} value={i.value}>
                {i.label}
                <span className={cn("ml-auto pl-3 text-[11px]", i.paid ? "text-paid" : "text-free")}>{i.paid ? "paid" : "free"}</span>
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
      <Textarea value={draft.motion.prompt} onChange={(e) => set((s) => void (s.motion.prompt = e.target.value))} placeholder="Only the motion and the camera" className="min-h-14 text-[13px]" />
      {(mode === "masked_i2v" || mode === "cinemagraph") && (
        <Input
          value={draft.motion.mask?.target ?? ""}
          onChange={(e) => set((s) => void (s.motion.mask = { ...s.motion.mask, target: e.target.value, regions: undefined }))}
          placeholder="What should move, in words (e.g. the steam above the cups)"
        />
      )}
      {mode === "flf_inbetween" && (
        <Textarea
          value={draft.motion.end_keyframe?.prompt ?? ""}
          onChange={(e) => set((s) => void (s.motion.end_keyframe = { ...s.motion.end_keyframe!, prompt: e.target.value }))}
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
