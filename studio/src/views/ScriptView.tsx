import { Sparkles } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { api, diff, type Shot, type Storyboard } from "@/api"
import type { Studio } from "@/App"
import { ProvidersPanel } from "@/components/providers-panel"
import { RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { FREE, fieldLabel } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { ApproveBar, Page, Section, StepHeader } from "@/views/parts"

/** The words of a scene: what the script step covers. */
const words = (s: Shot) => ({ beat: s.beat, duration_s: s.duration_s, lines: s.lines })

export function ScriptView({ studio }: { studio: Studio }) {
  const { state, flow, track, busy, go } = studio
  const sb = state.storyboard
  const step = flow.steps.find((s) => s.id === "script")!
  return (
    <Page>
      <StepHeader n={2} title="Script" lead="The film in words: each scene, who speaks, the lines and their English subtitles. Edit lines here, or say what to change and let Gemini revise.">
        <div className="flex items-center gap-2">
          <RunButton
            variant={sb ? "secondary" : "default"}
            cost={FREE("Gemini", "writing")}
            disabled={busy || step.locked}
            onRun={() => track(api.draftScript())}
            confirm={
              sb
                ? {
                    title: "Draft the whole script again?",
                    body: "Gemini writes every scene again from the story. Your edits to scenes are replaced; the old storyboard is kept as a backup in outputs/script.",
                    action: "Draft again",
                  }
                : undefined
            }
          >
            {sb ? "Draft again" : "Draft the script"}
          </RunButton>
          {step.state === "approved" && (
            <Button onClick={() => go("sketch")}>
              Go to Sketch
            </Button>
          )}
        </div>
      </StepHeader>
      <ProvidersPanel studio={studio} step="script" />
      <ApproveBar studio={studio} step="script" what="the script" />
      {!sb ? (
        <p className="text-muted-foreground">No script yet. Draft it from the story; it takes about a minute.</p>
      ) : (
        <>
          <Revise studio={studio} sb={sb} />
          <Section title={`${sb.shots.length} scenes`} aside={<span className="text-[12px] text-subtle">{sb.shots.reduce((n, s) => n + s.duration_s, 0)} s planned, plus the end card</span>}>
            <div className="divide-y border-y">
              {sb.shots.map((s) => (
                <SceneWords key={s.id} studio={studio} shot={s} sb={sb} />
              ))}
            </div>
          </Section>
        </>
      )}
    </Page>
  )
}

function Revise({ studio, sb }: { studio: Studio; sb: Storyboard }) {
  const { refresh, busy } = studio
  const [text, setText] = useState("")
  const [writing, setWriting] = useState(false)
  const [proposal, setProposal] = useState<{ sb: Storyboard; errors: string[] } | null>(null)

  async function ask() {
    setWriting(true)
    try {
      const res = await api.reviseScript(text)
      setProposal({ sb: res.proposal, errors: res.errors })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setWriting(false)
    }
  }

  async function accept() {
    try {
      await api.acceptScript(proposal!.sb)
      toast.success("Revision saved")
      setProposal(null)
      setText("")
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const before = sb.shots.map(words)
  const after = proposal?.sb.shots.map(words) ?? []
  const changes = proposal
    ? after.flatMap((a, i) => diff(before[i] ?? {}, a).map((c) => ({ ...c, scene: proposal.sb.shots[i].id })))
    : []
  return (
    <div className="rounded-lg border p-4">
      <div className="mb-2 flex items-center gap-2 text-[13px] font-medium">
        <Sparkles className="size-4 text-primary" /> Ask for a revision
      </div>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="In plain words, e.g. “Make the ending shorter and let the mother speak in the market scene.”"
        className="min-h-16 text-[13px]"
      />
      <div className="mt-2 flex items-center gap-2">
        <RunButton size="sm" cost={FREE("Gemini", "writing")} disabled={busy || writing || !text.trim()} onRun={ask}>
          {writing ? "Gemini is writing…" : "Revise the script"}
        </RunButton>
        <span className="text-[12px] text-subtle">Nothing changes until you accept it.</span>
      </div>
      {proposal && (
        <div className="mt-4 border-t pt-4">
          <div className="mb-2 text-[13px] font-medium">
            {proposal.sb.shots.length} scenes{proposal.sb.shots.length !== sb.shots.length && ` (was ${sb.shots.length})`} · {changes.length} change
            {changes.length === 1 ? "" : "s"}
          </div>
          <ul className="max-h-80 space-y-2 overflow-y-auto text-[13px]">
            {changes.map((c) => (
              <li key={`${c.scene}.${c.path}`} className="grid grid-cols-[48px_160px_minmax(0,1fr)] gap-3">
                <span className="font-mono text-subtle">{c.scene}</span>
                <span className="text-muted-foreground">{fieldLabel(c.path)}</span>
                <span>
                  <span className="text-subtle line-through">{c.before}</span> {c.after}
                </span>
              </li>
            ))}
          </ul>
          {proposal.errors.length > 0 && (
            <ul className="mt-3 space-y-1 rounded-md border border-destructive/40 bg-destructive/10 p-2.5 text-[12.5px] text-destructive">
              {proposal.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex gap-2">
            <Button size="sm" disabled={proposal.errors.length > 0} onClick={accept}>
              Accept revision
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setProposal(null)}>
              Discard
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function SceneWords({ studio, shot, sb }: { studio: Studio; shot: Shot; sb: Storyboard }) {
  const { refresh } = studio
  const [draft, setDraft] = useState(shot)
  useEffect(() => setDraft(shot), [shot])
  const dirty = JSON.stringify(words(draft)) !== JSON.stringify(words(shot))
  const names = Object.fromEntries(sb.characters.map((c) => [c.id, c.name]))
  const setLine = (i: number, key: "text" | "en", value: string) =>
    setDraft({ ...draft, lines: draft.lines.map((l, n) => (n === i ? { ...l, [key]: value } : l)) })

  async function save() {
    try {
      await api.saveShot(draft)
      toast.success(`${shot.id} saved`)
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className={cn("grid grid-cols-[56px_minmax(0,1fr)] gap-4 py-4", dirty && "bg-primary/4")}>
      <div>
        <div className="font-mono text-[13px] font-medium">{shot.id}</div>
        <div className="mt-1 flex items-center gap-1 text-[12px] text-subtle">
          <input
            type="number"
            min={2}
            max={12}
            value={draft.duration_s}
            onChange={(e) => setDraft({ ...draft, duration_s: Number(e.target.value) })}
            className="w-8 bg-transparent tabular-nums outline-none focus:text-foreground"
            aria-label={`${shot.id} length in seconds`}
          />
          s
        </div>
      </div>
      <div className="min-w-0 space-y-2">
        <Input value={draft.beat} onChange={(e) => setDraft({ ...draft, beat: e.target.value })} className="border-transparent bg-transparent px-0 font-medium shadow-none hover:border-input focus-visible:px-2" />
        <div className="text-[12px] text-subtle">
          {sb.locations.find((p) => p.id === shot.location)?.name}
          {shot.characters.length > 0 && ` · ${shot.characters.map((c) => names[c]).join(", ")}`}
        </div>
        {draft.lines.map((l, i) => (
          <div key={i} className="grid grid-cols-[140px_minmax(0,1fr)_minmax(0,1fr)] items-center gap-2">
            <span className="truncate text-[12.5px] text-muted-foreground">{names[l.speaker] ?? l.speaker}</span>
            <Input lang="am" value={l.text} onChange={(e) => setLine(i, "text", e.target.value)} className="text-[14px]" />
            <Input value={l.en} onChange={(e) => setLine(i, "en", e.target.value)} className="text-[13px]" />
          </div>
        ))}
        {draft.lines.length === 0 && <div className="text-[12.5px] text-subtle">No lines: music only.</div>}
        {dirty && (
          <div className="flex gap-2 pt-1">
            <Button size="sm" onClick={save}>
              Save {shot.id}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setDraft(shot)}>
              Discard
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
