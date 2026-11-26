import { Pause, Play, RotateCcw, SlidersHorizontal } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { api, type Character, type Shot, type ShotState, type Tune } from "@/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

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
export function clean(t: Tune | undefined | null): Tune {
  const out: Tune = {}
  for (const f of FIELDS) {
    const v = t?.[f.id]
    if (v != null && v !== f.neutral) out[f.id] = v
  }
  return out
}

export const same = (a: Tune | null | undefined, b: Tune | null | undefined) =>
  (a == null) === (b == null) && JSON.stringify(clean(a ?? {})) === JSON.stringify(clean(b ?? {}))

function words(t: Tune): string {
  const parts = FIELDS.filter((f) => t[f.id] != null && t[f.id] !== f.neutral).map((f) => f.show(t[f.id]!))
  return parts.join(" · ")
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
 * Each line of the scene: its take, its words and subtitle, and how its voice is tuned.
 * Tuning is per line, or for every line the speaker has (the character's default). Edits go
 * into the scene panel's draft; the redo there saves and applies them.
 */
export function VoiceLines({
  shot,
  draft,
  media,
  cast,
  voices,
  savedVoices,
  others,
  onLines,
  onVoice,
}: {
  shot: Shot
  draft: Shot
  media: ShotState
  cast: Record<string, Character>
  /** Speakers' default tunings as edited, and as saved. */
  voices: Record<string, Tune>
  savedVoices: Record<string, Tune>
  /** How many lines elsewhere in the film follow this speaker's default. */
  others: (speaker: string) => number
  onLines: (fn: (lines: Shot["lines"]) => void) => void
  onVoice: (speaker: string, tune: Tune) => void
}) {
  const player = usePlayer()
  const [open, setOpen] = useState<number | null>(null)
  const [previews, setPreviews] = useState<Record<number, { audio: string; seconds: number; tune: string }>>({})
  const [loading, setLoading] = useState<number | null>(null)
  const effective = (i: number): Tune => ({ ...(voices[draft.lines[i].speaker] ?? {}), ...(draft.lines[i].tune ?? {}) })

  async function listen(i: number) {
    const tune = clean(effective(i))
    const sig = JSON.stringify(tune)
    const have = previews[i]
    if (have?.tune === sig) return player.play(`tuned:${i}`, have.audio)
    setLoading(i)
    try {
      const out = await api.previewVoice(`${shot.id}_L${i + 1}`, tune)
      setPreviews((p) => ({ ...p, [i]: { ...out, tune: sig } }))
      player.play(`tuned:${i}`, out.audio)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="space-y-4">
      {draft.lines.map((line, i) => {
        const take = media.lines[i]
        const saved = shot.lines[i]
        const name = cast[line.speaker]?.name ?? line.speaker
        const heard = take?.cer != null ? Math.round((1 - Math.min(1, take.cer)) * 100) : null
        const own = line.tune != null
        const tuned = words(effective(i))
        const tuneEdited = !same(line.tune, saved?.tune) || !same(voices[line.speaker], savedVoices[line.speaker])
        const isOpen = open === i
        const rest = others(line.speaker)
        return (
          <div key={i} className="space-y-1.5">
            <div className="flex items-center gap-2 text-[12px]">
              <Button
                variant="ghost"
                size="icon-xs"
                className="-ml-1"
                disabled={!take?.audio}
                aria-label={`Play ${name}'s take`}
                title={take?.audio ? "Play the saved take" : "Not recorded yet"}
                onClick={() => take?.audio && player.play(`now:${i}`, take.audio)}
              >
                {player.playing === `now:${i}` ? <Pause /> : <Play />}
              </Button>
              <span className="font-medium">{name}</span>
              {take?.seconds != null && <span className="text-subtle tabular-nums">{take.seconds.toFixed(1)} s</span>}
              {heard != null && (
                <span className={cn("tabular-nums", heard < 65 ? "text-warn" : "text-subtle")} title={`Heard back: ${take?.heard ?? ""}`}>
                  {heard}% heard
                </span>
              )}
              <Button
                variant={isOpen ? "secondary" : "ghost"}
                size="xs"
                className={cn("ml-auto", tuneEdited && "text-primary")}
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : i)}
              >
                <SlidersHorizontal /> {tuned || "Tune"}
              </Button>
            </div>
            <Textarea
              value={line.text}
              lang="am"
              onChange={(e) => onLines((l) => void (l[i].text = e.target.value))}
              className="min-h-12 text-[15px]"
            />
            <Input value={line.en} onChange={(e) => onLines((l) => void (l[i].en = e.target.value))} placeholder="English subtitle" className="text-[13px]" />
            {isOpen && (
              <div className="space-y-3 rounded-lg bg-muted/50 p-3">
                <ToggleGroup
                  value={[own ? "own" : "all"]}
                  onValueChange={(v) => {
                    if (!v[0]) return
                    onLines((l) => {
                      if (v[0] === "own") l[i].tune = { speed: 1, pitch: 0, age: 0, ...(voices[line.speaker] ?? {}) }
                      else delete l[i].tune
                    })
                  }}
                  size="sm"
                  variant="outline"
                  spacing={0}
                  className="w-full bg-background"
                >
                  <ToggleGroupItem value="own" className="flex-1">
                    This line
                  </ToggleGroupItem>
                  <ToggleGroupItem value="all" className="flex-1" title={rest ? `Also ${rest} line${rest === 1 ? "" : "s"} in other scenes` : undefined}>
                    All of {name}'s lines{rest ? ` (+${rest})` : ""}
                  </ToggleGroupItem>
                </ToggleGroup>
                <TuneSliders
                  tune={own ? line.tune! : (voices[line.speaker] ?? {})}
                  onChange={(t) => (own ? onLines((l) => void (l[i].tune = t)) : onVoice(line.speaker, t))}
                />
                <Button variant="outline" size="sm" disabled={!take?.previewable || loading != null} onClick={() => listen(i)}>
                  {player.playing === `tuned:${i}` ? <Pause /> : <Play />} {loading === i ? "Rendering…" : "Listen tuned"}
                </Button>
                {!take?.previewable && <span className="ml-2 text-[12px] text-subtle">Record the line first</span>}
              </div>
            )}
          </div>
        )
      })}
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
