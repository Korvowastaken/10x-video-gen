import { useEffect, useState } from "react"
import { toast } from "sonner"

import { api, type Choices, type Settings } from "@/api"
import type { Studio } from "@/App"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { ApproveBar, NextStep, Page, StepHeader } from "@/views/parts"

const LOOK_LABEL: Record<string, string> = { "low-poly-3d": "Low-poly 3D", "painted-2d": "Painted 2D", claymation: "Claymation" }

export function StoryView({ studio }: { studio: Studio }) {
  const { flow, refresh, go } = studio
  const [text, setText] = useState(flow.story_text)
  const dirty = text !== flow.story_text
  useEffect(() => setText(flow.story_text), [flow.story_text])

  async function save() {
    await api.saveStoryText(text)
    toast.success("Story saved")
    await refresh()
  }

  return (
    <Page>
      <StepHeader n={1} title="Story" lead="Write or paste the family story in plain words, in any language. Change the settings on the right only if the defaults don't fit.">
        {flow.steps[0].state === "approved" && <NextStep to="Script" onClick={() => go("script")} />}
      </StepHeader>
      <ApproveBar studio={studio} step="story" what="the story" />
      <div className="grid grid-cols-[minmax(0,1fr)_280px] gap-8">
        <div>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoFocus={!flow.story_text.trim()}
            aria-label="Your story"
            placeholder="Every Saturday when she was a girl, my grandmother walked to the market…"
            className="min-h-[calc(100vh-300px)] text-[14px] leading-7"
          />
          <div className="mt-2 flex items-center gap-3">
            <Button onClick={save} disabled={!dirty}>
              Save story
            </Button>
            <span className="text-[12px] text-subtle">
              {dirty ? "Unsaved changes" : `${text.trim().split(/\s+/).filter(Boolean).length} words`}
            </span>
          </div>
        </div>
        <SettingsPanel studio={studio} />
      </div>
    </Page>
  )
}

function SettingsPanel({ studio }: { studio: Studio }) {
  const { flow, refresh } = studio
  const [choices, setChoices] = useState<Choices | null>(null)
  const [draft, setDraft] = useState<Settings>(flow.settings)
  useEffect(() => void api.choices().then(setChoices), [])
  useEffect(() => setDraft(flow.settings), [flow.settings])
  const changed = (["language", "look", "target_seconds", "audience", "feel"] as const).some((k) => draft[k] !== flow.settings[k])

  async function save() {
    try {
      await api.saveSettings({
        language: draft.language,
        look: draft.look,
        target_seconds: Number(draft.target_seconds),
        audience: draft.audience,
        feel: draft.feel,
      })
      toast.success("Settings saved")
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  if (!choices) return <aside />
  const languages = Object.entries(choices.languages).map(([value, label]) => ({ value, label }))
  const looks = choices.looks.map((value) => ({ value, label: LOOK_LABEL[value] ?? value }))
  return (
    <aside className="space-y-4">
      <h2 className="text-[13px] font-semibold">Settings</h2>
      <Setting label="Spoken language" hint="Subtitles are always English">
        <Select items={languages} value={draft.language} onValueChange={(v) => setDraft({ ...draft, language: String(v) })}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {languages.map((l) => (
              <SelectItem key={l.value} value={l.value}>
                {l.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Setting>
      <Setting label="Look">
        <Select items={looks} value={draft.look} onValueChange={(v) => setDraft({ ...draft, look: String(v) })}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {looks.map((l) => (
              <SelectItem key={l.value} value={l.value}>
                {l.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Setting>
      <Setting label="Length" hint="60 to 90 seconds">
        <Input
          type="number"
          min={60}
          max={90}
          value={draft.target_seconds}
          onChange={(e) => setDraft({ ...draft, target_seconds: Number(e.target.value) })}
        />
      </Setting>
      <Setting label="Who watches">
        <Input value={draft.audience} placeholder="Gemini guesses from the story" onChange={(e) => setDraft({ ...draft, audience: e.target.value })} />
      </Setting>
      <Setting label="How it should feel at the end">
        <Input value={draft.feel} placeholder="Gemini guesses from the story" onChange={(e) => setDraft({ ...draft, feel: e.target.value })} />
      </Setting>
      <Button variant="secondary" className="w-full" disabled={!changed} onClick={save}>
        Save settings
      </Button>
    </aside>
  )
}

function Setting({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-[12.5px] text-secondary-foreground">{label}</span>
        {hint && <span className="text-[11.5px] text-subtle">{hint}</span>}
      </span>
      {children}
    </label>
  )
}
