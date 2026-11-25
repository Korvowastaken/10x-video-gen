import { Pause, Play, RotateCcw } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { api, type Character, type Shot, type ShotState, type Tune } from "@/api"
import type { Studio } from "@/App"
import { CostTag, RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { FREE } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { StatusDot } from "@/views/parts"

type Field = keyof Tune
/** Same ranges as pipeline/tuning.py RANGES. */
const FIELDS: { id: Field; label: string; min: number; max: number; step: number; neutral: number; show: (v: number) => string }[] = [
  { id: "speed", label: "Speed", min: 0.75, max: 1.35, step: 0.01, neutral: 1, show: (v) => `${v.toFixed(2)}×` },
  { id: "pitch", label: "Pitch", min: -4, max: 4, step: 0.5, neutral: 0, show: (v) => (v === 0 ? "0 st" : `${v > 0 ? "+" : "−"}${Math.abs(v)} st`) },
  {
    id: "age",
    label: "Age",
    min: -1,
    max: 1,
    step: 0.05,
    neutral: 0,
    show: (v) => (v === 0 ? "As recorded" : `${v > 0 ? "Older" : "Younger"} ${Math.round(Math.abs(v) * 100)}%`),
  },
]

/** Neutral fields dropped, like tuning.normalise: {} is "as recorded". */
function clean(t: Tune | undefined): Tune {
  const out: Tune = {}
  for (const f of FIELDS) {
    const v = t?.[f.id]
    if (v != null && v !== f.neutral) out[f.id] = v
  }
  return out
}
const same = (a: Tune | null | undefined, b: Tune | null | undefined) =>
  (a == null) === (b == null) && JSON.stringify(clean(a ?? {})) === JSON.stringify(clean(b ?? {}))
function words(t: Tune): string {
  const parts = FIELDS.filter((f) => t[f.id] != null && t[f.id] !== f.neutral).map((f) => f.show(t[f.id]!))
  return parts.length ? parts.join(" · ") : "As recorded"
}

/** One shared player, so starting a line stops the last one. */
function usePlayer() {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState<string | null>(null)
  useEffect(() => () => audio.current?.pause(), [])
  function play(id: string, url: string) {
    audio.current?.pause()
    if (playing === id) return setPlaying(null)
    const a = new Audio(url)
    audio.current = a
    a.onended = () => setPlaying((p) => (p === id ? null : p))
    setPlaying(id)
    void a.play().catch(() => setPlaying(null))
  }
  return { playing, play }
}

/**
 * Speed, pitch and age for each voice: per character (every line they speak) and per line.
 * Gender stays with the TTS voice; this only shapes its feel. Everything here re-renders the
 * saved take with FFmpeg, so it is free and spends no voice quota.
 */
export function VoicePanel({ studio, shot, media }: { studio: Studio; shot: Shot; media: ShotState }) {
  const sb = studio.state.storyboard!
  const cast = useMemo(() => Object.fromEntries(sb.characters.map((c) => [c.id, c])), [sb.characters])
  const speakers = useMemo(() => [...new Set(shot.lines.map((l) => l.speaker))].map((id) => cast[id]).filter(Boolean), [shot.lines, cast])
  const savedChars = useMemo(() => Object.fromEntries(speakers.map((c) => [c.id, c.voice.tune ?? {}])), [speakers])
  const savedLines = useMemo(() => shot.lines.map((l) => l.tune ?? null), [shot.lines])
  const [chars, setChars] = useState<Record<string, Tune>>(savedChars)
  const [lines, setLines] = useState<(Tune | null)[]>(savedLines)
  const key = JSON.stringify([savedChars, savedLines])
  useEffect(() => {
    setChars(savedChars)
    setLines(savedLines)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  const player = usePlayer()
  const [previews, setPreviews] = useState<Record<string, { audio: string; seconds: number; tune: string }>>({})
  const [loading, setLoading] = useState<string | null>(null)

  const changedChars = speakers.filter((c) => !same(chars[c.id], savedChars[c.id]))
  const changedLines = lines.map((t, i) => (same(t, savedLines[i]) ? null : i)).filter((i): i is number => i != null)
  const dirty = changedChars.length + changedLines.length > 0
  const effective = (i: number): Tune => ({ ...(chars[shot.lines[i].speaker] ?? {}), ...(lines[i] ?? {}) })
  const wasEffective = (i: number): Tune => ({ ...(savedChars[shot.lines[i].speaker] ?? {}), ...(savedLines[i] ?? {}) })
  const rerender = shot.lines.filter((_, i) => !same(effective(i), wasEffective(i))).length
  /** Lines in other scenes that follow this character's default (no own tuning), and whether each has a take to re-tune. */
  const others = (cid: string) =>
    sb.shots.flatMap((s) =>
      s.id === shot.id ? [] : s.lines.map((l, i) => ({ l, tunable: !!studio.state.shots.find((m) => m.id === s.id)?.lines[i]?.previewable })),
    ).filter(({ l }) => l.speaker === cid && !l.tune)
  const otherLines = (cid: string) => others(cid).length
  // Lines elsewhere in the film follow a changed default too; those without a current take wait for one.
  const elsewhere = changedChars.reduce((n, c) => n + others(c.id).filter((o) => o.tunable).length, 0)
  const waiting = changedChars.reduce((n, c) => n + others(c.id).filter((o) => !o.tunable).length, 0)
  const unapplied = shot.lines.map((_, i) => !!media.lines[i]?.previewable && !same(media.lines[i].applied, media.lines[i].tune))

  async function listen(i: number) {
    const item = `${shot.id}_L${i + 1}`
    const tune = clean(effective(i))
    const sig = JSON.stringify(tune)
    const have = previews[item]
    if (have?.tune === sig) return player.play(`tuned:${i}`, have.audio)
    setLoading(item)
    try {
      const out = await api.previewVoice(item, tune)
      setPreviews((p) => ({ ...p, [item]: { ...out, tune: sig } }))
      player.play(`tuned:${i}`, out.audio)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(null)
    }
  }

  async function apply() {
    const body = {
      characters: Object.fromEntries(changedChars.map((c) => [c.id, clean(chars[c.id])])),
      lines: Object.fromEntries(changedLines.map((i) => [`${shot.id}_L${i + 1}`, lines[i]])),
    }
    await studio.track(api.tuneVoices(body))
  }

  if (!shot.lines.length) return <p className="text-[13px] text-muted-foreground">No spoken line in this scene.</p>

  return (
    <div>
      <p className="mb-5 max-w-xl text-[12.5px] text-muted-foreground">
        Shapes how each voice sounds. The voice itself, and so whether it is a man or a woman, stays as picked; this re-renders the saved take on this
        computer, so it never spends voice quota. <CostTag cost={FREE()} className="ml-1 align-[1px]" />
      </p>

      <h3 className="mb-2 text-[13px] font-semibold">Character defaults</h3>
      <div className="divide-y rounded-lg border">
        {speakers.map((c) => (
          <CharacterRow
            key={c.id}
            character={c}
            tune={chars[c.id] ?? {}}
            changed={!same(chars[c.id], savedChars[c.id])}
            others={otherLines(c.id)}
            onChange={(t) => setChars((x) => ({ ...x, [c.id]: t }))}
          />
        ))}
      </div>

      <h3 className="mt-7 mb-2 text-[13px] font-semibold">This scene's lines</h3>
      <div className="divide-y rounded-lg border">
        {shot.lines.map((line, i) => {
          const take = media.lines[i]
          const own = lines[i]
          const name = cast[line.speaker]?.name ?? line.speaker
          const preview = previews[`${shot.id}_L${i + 1}`]
          const fresh = preview && preview.tune === JSON.stringify(clean(effective(i)))
          return (
            <div key={i} className="px-3.5 py-3">
              <div className="flex items-center gap-2 text-[12px]">
                <span className="font-medium">{name}</span>
                <span className="text-subtle">Line {i + 1}</span>
                {unapplied[i] ? (
                  <StatusDot status="stale" className="ml-auto">
                    Tuning not applied
                  </StatusDot>
                ) : (
                  !same(own, savedLines[i]) && <span className="ml-auto text-[11.5px] text-primary">Edited</span>
                )}
              </div>
              <p lang="am" className="mt-1 text-[13.5px] leading-snug">
                {line.text}
              </p>
              <p className="text-[12px] text-subtle">{line.en}</p>

              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <ToggleGroup
                  value={[own ? "own" : "default"]}
                  onValueChange={(v) => {
                    if (!v[0]) return
                    setLines((x) => x.map((t, j) => (j !== i ? t : v[0] === "own" ? { speed: 1, pitch: 0, age: 0, ...(chars[line.speaker] ?? {}) } : null)))
                  }}
                  size="sm"
                  variant="outline"
                  spacing={0}
                >
                  <ToggleGroupItem value="default">Character default</ToggleGroupItem>
                  <ToggleGroupItem value="own">Own for this line</ToggleGroupItem>
                </ToggleGroup>
                {!own && <span className="text-[12px] text-subtle">{words(chars[line.speaker] ?? {})}</span>}
              </div>
              {own && (
                <div className="mt-3">
                  <TuneSliders tune={own} onChange={(t) => setLines((x) => x.map((y, j) => (j === i ? t : y)))} />
                </div>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!take?.audio}
                  onClick={() => take?.audio && player.play(`now:${i}`, take.audio)}
                >
                  {player.playing === `now:${i}` ? <Pause /> : <Play />} As saved
                  {take?.seconds != null && <span className="text-subtle tabular-nums">{take.seconds.toFixed(1)} s</span>}
                </Button>
                <Button variant="outline" size="sm" disabled={!take?.previewable || loading != null} onClick={() => listen(i)}>
                  {player.playing === `tuned:${i}` ? <Pause /> : <Play />} {loading === `${shot.id}_L${i + 1}` ? "Rendering…" : "With these settings"}
                  {fresh && <span className="text-subtle tabular-nums">{preview.seconds.toFixed(1)} s</span>}
                </Button>
                {!take?.previewable ? (
                  <span className="text-[12px] text-subtle">Record this line first: there is no saved take yet.</span>
                ) : (
                  !take.tunable && (
                    <span className="text-[12px] text-subtle">Older take: tuning applies to it now and carries over when the line is recorded again.</span>
                  )
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="sticky bottom-0 z-10 mt-5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t bg-background/95 py-3 backdrop-blur">
        <RunButton cost={FREE()} disabled={!dirty || studio.busy || studio.flow.steps[4].locked} onRun={apply}>
          Apply tuning
        </RunButton>
        <Button variant="ghost" disabled={!dirty} onClick={() => (setChars(savedChars), setLines(savedLines))}>
          Discard
        </Button>
        <span className="text-[12px] text-muted-foreground">
          {dirty
            ? `Re-renders ${rerender} line${rerender === 1 ? "" : "s"} here${elsewhere ? ` and ${elsewhere} in other scenes` : ""} from the saved takes${waiting ? `; ${waiting} more have no take yet` : ""}. A faster or slower line changes the scene's length in the cut.`
            : unapplied.some(Boolean)
              ? "Some lines are not rendered with their tuning yet."
              : "Play a line with new settings before you apply them."}
        </span>
        {!dirty && unapplied.some(Boolean) && (
          <RunButton cost={FREE()} variant="secondary" size="sm" disabled={studio.busy || studio.flow.steps[4].locked} onRun={() => studio.track(api.tuneVoices({}))}>
            Render them now
          </RunButton>
        )}
      </div>
    </div>
  )
}

function CharacterRow({
  character,
  tune,
  changed,
  others,
  onChange,
}: {
  character: Character
  tune: Tune
  changed: boolean
  others: number
  onChange: (t: Tune) => void
}) {
  return (
    <div className="px-3.5 py-3">
      <div className="mb-2 flex items-baseline gap-3 text-[12px]">
        <span className="shrink-0 text-[13px] font-medium">{character.name}</span>
        <span className="min-w-0 truncate text-subtle" title={character.voice.direction}>
          {character.voice.name} voice · {character.voice.direction}
        </span>
        <span className={cn("ml-auto shrink-0 whitespace-nowrap", changed ? "text-primary" : "text-subtle")}>
          {changed ? "Edited" : others ? `Also in ${others} line${others === 1 ? "" : "s"} elsewhere` : "Only in this scene"}
        </span>
      </div>
      <TuneSliders tune={tune} onChange={onChange} />
    </div>
  )
}

function TuneSliders({ tune, onChange }: { tune: Tune; onChange: (t: Tune) => void }) {
  return (
    <div className="space-y-2">
      {FIELDS.map((f) => {
        const v = tune[f.id] ?? f.neutral
        const moved = v !== f.neutral
        return (
          <div key={f.id} className="grid grid-cols-[44px_minmax(0,1fr)_92px_24px] items-center gap-3">
            <span className="text-[12px] text-muted-foreground">{f.label}</span>
            <Slider
              value={[v]}
              min={f.min}
              max={f.max}
              step={f.step}
              onValueChange={(x) => onChange({ ...tune, [f.id]: Array.isArray(x) ? x[0] : x })}
              mark={f.neutral}
              aria-label={f.label}
            />
            <span className={cn("text-right text-[12px] tabular-nums", moved ? "text-foreground" : "text-subtle")}>{f.show(v)}</span>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={`Reset ${f.label.toLowerCase()}`}
              className={cn(!moved && "invisible")}
              onClick={() => onChange({ ...tune, [f.id]: f.neutral })}
            >
              <RotateCcw />
            </Button>
          </div>
        )
      })}
    </div>
  )
}
