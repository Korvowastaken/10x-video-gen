import { Check, MessageSquareText, RotateCcw, Sparkles, X } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { ApiError, api, diff, MODES, type Shot, type ShotState } from "@/api"
import type { Studio } from "@/App"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

export function ScenesView({ studio }: { studio: Studio }) {
  const sb = studio.state.storyboard
  const [selected, setSelected] = useState(() => localStorage.getItem("scene") ?? sb?.shots[0]?.id ?? "")
  useEffect(() => localStorage.setItem("scene", selected), [selected])
  if (!sb) return <div className="p-10 text-muted-foreground">Draft the storyboard from your story first.</div>
  const shot = sb.shots.find((s) => s.id === selected) ?? sb.shots[0]
  const media = studio.state.shots.find((s) => s.id === shot.id)!
  return (
    <div className="grid lg:grid-cols-[300px_minmax(0,1fr)]">
      <SceneList studio={studio} selected={shot.id} onSelect={setSelected} />
      <SceneEditor key={shot.id} studio={studio} shot={shot} media={media} />
    </div>
  )
}

function SceneList({ studio, selected, onSelect }: { studio: Studio; selected: string; onSelect: (id: string) => void }) {
  const sb = studio.state.storyboard!
  const planned = studio.state.shots.reduce((sum, s) => sum + s.price, 0)
  return (
    <nav className="flex flex-wrap gap-1.5 border-b p-3 lg:sticky lg:flex-nowrap lg:top-0 lg:h-screen lg:flex-col lg:overflow-y-auto lg:border-r lg:border-b-0">
      <div className="hidden px-2 pt-2 pb-1 text-[12px] text-subtle lg:block">
        {sb.shots.length} scenes · ${planned.toFixed(2)} of motion planned
      </div>
      {sb.shots.map((s) => {
        const m = studio.state.shots.find((x) => x.id === s.id)!
        return (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded-lg border p-1.5 pr-2.5 text-left transition-colors hover:bg-muted lg:items-start lg:gap-3 lg:border-0 lg:p-2",
              selected === s.id && "bg-muted",
            )}
          >
            <div className="aspect-[9/16] w-6 shrink-0 lg:w-11 overflow-hidden rounded-md bg-secondary">
              {m.keyframe && <img src={m.keyframe} alt="" className="size-full object-cover" />}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] font-semibold">{s.id}</span>
                <ModeBadge mode={s.motion.mode} />
                {m.clip && <span className="size-1.5 rounded-full bg-free" title="Clip ready" />}
              </div>
              <p className="mt-1 line-clamp-2 hidden text-[12.5px] lg:block text-muted-foreground">{s.lines[0]?.en ?? s.beat}</p>
            </div>
          </button>
        )
      })}
    </nav>
  )
}

function ModeBadge({ mode }: { mode: string }) {
  const m = MODES[mode] ?? { label: mode, paid: false }
  return (
    <Badge variant="outline" className={cn("h-5 rounded-full px-2 text-[11px] font-medium", m.paid ? "border-paid/30 text-paid" : "border-free/30 text-free")}>
      {m.label}
    </Badge>
  )
}

function SceneEditor({ studio, shot, media }: { studio: Studio; shot: Shot; media: ShotState }) {
  const { refresh, track, busy } = studio
  const sb = studio.state.storyboard!
  const [draft, setDraft] = useState<Shot>(shot)
  const [errors, setErrors] = useState<string[]>([])
  const dirty = JSON.stringify(draft) !== JSON.stringify(shot)
  useEffect(() => {
    if (!dirty) setDraft(shot)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shot])
  const names = useMemo(() => Object.fromEntries(sb.characters.map((c) => [c.id, c.name])), [sb])

  const set = (fn: (s: Shot) => void) =>
    setDraft((prev) => {
      const next = structuredClone(prev)
      fn(next)
      return next
    })

  async function save(next: Shot = draft) {
    try {
      await api.saveShot(next)
      setErrors([])
      toast.success(`${shot.id} saved`)
      await refresh()
      return true
    } catch (err) {
      setErrors(err instanceof ApiError && err.errors.length ? err.errors : [(err as Error).message])
      return false
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-5 py-8 md:px-10">
      <div className="mb-1 flex items-center gap-3">
        <span className="font-mono text-[12px] text-subtle">{shot.id} · {shot.size} · {shot.duration_s}s planned</span>
        {media.used && media.used !== shot.motion.mode && (
          <span className="text-[12px] text-warn">last cut used {MODES[media.used]?.label ?? media.used}</span>
        )}
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">{shot.beat}</h1>
      <p className="mt-1 text-muted-foreground">{shot.reason}</p>

      <Media media={media} />

      <Section title="Lines">
        {draft.lines.length === 0 && <p className="text-muted-foreground">No spoken line in this scene.</p>}
        {draft.lines.map((line, i) => {
          const take = media.lines[i]
          return (
            <div key={i} className="rounded-xl border bg-card p-3">
              <div className="mb-2 flex items-center gap-2 text-[12px]">
                <span className="font-medium">{names[line.speaker] ?? line.speaker}</span>
                {take?.seconds && <span className="text-subtle">{take.seconds.toFixed(1)}s</span>}
                {take?.cer != null && (
                  <span className={cn("ml-auto font-mono", take.cer > 0.35 ? "text-warn" : "text-subtle")} title={take.heard ?? ""}>
                    listen-back {Math.round((1 - Math.min(1, take.cer)) * 100)}%
                  </span>
                )}
              </div>
              <Textarea
                value={line.text}
                lang="am"
                onChange={(e) => set((s) => void (s.lines[i].text = e.target.value))}
                className="min-h-14 text-[15px]"
              />
              <Input
                value={line.en}
                onChange={(e) => set((s) => void (s.lines[i].en = e.target.value))}
                className="mt-2"
                placeholder="English subtitle"
              />
              {take?.audio && <audio controls src={take.audio} className="mt-3 h-8 w-full" />}
            </div>
          )
        })}
      </Section>

      <Section title="Picture">
        <Textarea
          value={draft.keyframe.prompt}
          onChange={(e) => set((s) => void (s.keyframe.prompt = e.target.value))}
          className="min-h-20 text-[13px]"
        />
      </Section>

      <Section title="Motion">
        <MotionEditor draft={draft} set={set} />
      </Section>

      {errors.length > 0 && (
        <ul className="mt-4 space-y-1 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-[13px] text-destructive">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex gap-2">
        <Button onClick={() => save()} disabled={!dirty}>
          Save scene
        </Button>
        <Button variant="ghost" onClick={() => (setDraft(shot), setErrors([]))} disabled={!dirty}>
          Discard edits
        </Button>
      </div>

      <FeedbackPanel shot={shot} disabled={dirty} onAccept={save} />
      <RedoPanel studio={studio} shot={shot} media={media} disabled={busy || dirty} onRedo={(parts) => track(api.redo(shot.id, parts))} />
    </div>
  )
}

function Media({ media }: { media: ShotState }) {
  const tiles: [string, string | null, "img" | "video"][] = [
    ["Still", media.keyframe, "img"],
    ["End frame", media.end, "img"],
    ["Clip", media.clip, "video"],
  ]
  return (
    <div className="mt-6 grid grid-cols-3 gap-3 sm:max-w-xl">
      {tiles
        .filter(([label, url]) => url || label !== "End frame")
        .map(([label, url, kind]) => (
          <figure key={label}>
            <div className="aspect-[9/16] overflow-hidden rounded-lg border bg-secondary">
              {url && kind === "img" && <img src={url} alt={label} className="size-full object-cover" />}
              {url && kind === "video" && <video src={url} className="size-full object-cover" autoPlay loop muted playsInline />}
              {!url && <div className="grid size-full place-items-center text-[12px] text-subtle">none yet</div>}
            </div>
            <figcaption className="mt-1.5 text-[12px] text-subtle">{label}</figcaption>
          </figure>
        ))}
    </div>
  )
}

function MotionEditor({ draft, set }: { draft: Shot; set: (fn: (s: Shot) => void) => void }) {
  const mode = draft.motion.mode
  const items = Object.entries(MODES).map(([value, m]) => ({ value, label: `${m.label}${m.paid ? " · paid" : ""}` }))
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
              if (value === "flf_inbetween" && !s.motion.end_keyframe)
                s.motion.end_keyframe = { prompt: "Same place and camera: ", seed: s.keyframe.seed + 1 }
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
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {MODES[mode]?.paid && (
          <div className="flex rounded-lg border p-0.5 text-[12px]">
            {[5, 8].map((n) => (
              <button
                key={n}
                onClick={() => set((s) => void (s.motion.clip_s = n))}
                className={cn("rounded-md px-2.5 py-1", (draft.motion.clip_s ?? 5) === n ? "bg-muted text-foreground" : "text-muted-foreground")}
              >
                {n} s clip
              </button>
            ))}
          </div>
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
        <div className="flex flex-wrap gap-1.5">
          {["push-in", "pull-out", "slide-left", "slide-right", "rise"].map((move) => (
            <Chip key={move} on={(draft.motion.parallax?.move ?? "push-in") === move} onClick={() => set((s) => void (s.motion.parallax = { ...s.motion.parallax, move }))}>
              {move}
            </Chip>
          ))}
        </div>
      )}
      {mode === "still_kenburns" && (
        <div className="flex flex-wrap gap-1.5">
          {["zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down"].map((k) => (
            <Chip key={k} on={(draft.motion.kenburns ?? "zoom-in") === k} onClick={() => set((s) => void (s.motion.kenburns = k))}>
              {k}
            </Chip>
          ))}
        </div>
      )}
    </div>
  )
}

function FeedbackPanel({ shot, disabled, onAccept }: { shot: Shot; disabled: boolean; onAccept: (s: Shot) => Promise<boolean> }) {
  const [text, setText] = useState("")
  const [loading, setLoading] = useState(false)
  const [proposal, setProposal] = useState<{ shot: Shot; errors: string[] } | null>(null)
  const changes = proposal ? diff(shot, proposal.shot) : []

  async function ask() {
    setLoading(true)
    try {
      const res = await api.feedback(shot.id, text)
      setProposal({ shot: res.proposal, errors: res.errors })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Section title="Feedback" icon={<MessageSquareText className="size-4" />}>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="What should change in this scene? e.g. 'Grandma should be laughing, and the line should mention Sunday.'"
        className="min-h-20 text-[13px]"
      />
      <div className="flex items-center gap-2">
        <Button onClick={ask} disabled={!text.trim() || loading || disabled}>
          <Sparkles /> {loading ? "Revising…" : "Revise with Gemini"}
        </Button>
        {disabled && <span className="text-[12px] text-subtle">Save or discard your edits first</span>}
      </div>
      {proposal && (
        <div className="rounded-xl border bg-card p-4">
          <div className="mb-3 text-[13px] font-medium">Proposed changes</div>
          {changes.length === 0 && <p className="text-[13px] text-muted-foreground">No changes proposed.</p>}
          <div className="space-y-3">
            {changes.map((c) => (
              <div key={c.path} className="text-[13px]">
                <div className="mb-1 font-mono text-[11px] text-subtle">{c.path}</div>
                <div className="rounded-md bg-destructive/10 px-2 py-1 text-muted-foreground line-through decoration-destructive/40">{c.before}</div>
                <div className="mt-1 rounded-md bg-free/10 px-2 py-1">{c.after}</div>
              </div>
            ))}
          </div>
          {proposal.errors.length > 0 && (
            <ul className="mt-3 text-[12.5px] text-destructive">
              {proposal.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex gap-2">
            <Button
              disabled={proposal.errors.length > 0 || changes.length === 0}
              onClick={async () => {
                if (await onAccept(proposal.shot)) {
                  setProposal(null)
                  setText("")
                }
              }}
            >
              <Check /> Accept
            </Button>
            <Button variant="ghost" onClick={() => setProposal(null)}>
              <X /> Discard
            </Button>
          </div>
        </div>
      )}
    </Section>
  )
}

function RedoPanel({ shot, media, disabled, onRedo }: { studio: Studio; shot: Shot; media: ShotState; disabled: boolean; onRedo: (parts: string[]) => void }) {
  const [parts, setParts] = useState<string[]>([])
  const toggle = (p: string) => setParts((x) => (x.includes(p) ? x.filter((y) => y !== p) : [...x, p]))
  const paid = MODES[shot.motion.mode]?.paid
  const options = [
    { id: "keyframe", label: shot.motion.mode === "flf_inbetween" ? "Still + end frame" : "Still", note: "free" },
    { id: "voice", label: "Voice", note: shot.lines.length ? "free tier" : "no line", off: !shot.lines.length },
    { id: "clip", label: "Clip", note: paid ? `$${media.price.toFixed(2)}` : "free motion, made at assembly", off: !paid },
  ]
  return (
    <Section title="Redo this scene" icon={<RotateCcw className="size-4" />}>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <Chip key={o.id} on={parts.includes(o.id)} disabled={o.off} onClick={() => toggle(o.id)}>
            {o.label} <span className="text-subtle">· {o.note}</span>
          </Chip>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={() => onRedo(parts)} disabled={disabled || parts.length === 0}>
          Redo {parts.length ? parts.join(" + ") : "scene"}
        </Button>
        {parts.includes("clip") && <span className="text-[12px] text-paid">Buys one clip at WaveSpeed</span>}
      </div>
      <p className="text-[12px] text-subtle">Then assemble the film to see it in the cut. Only this scene is regenerated.</p>
    </Section>
  )
}

function Section({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mt-9">
      <h2 className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-muted-foreground">
        {icon}
        {title}
      </h2>
      <div className="grid gap-3">{children}</div>
    </section>
  )
}

function Chip({ on, disabled, onClick, children }: { on: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-full border px-3 py-1 text-[12.5px] transition-colors disabled:opacity-40",
        on ? "border-primary bg-accent text-foreground" : "text-muted-foreground hover:bg-muted",
      )}
    >
      {children}
    </button>
  )
}
