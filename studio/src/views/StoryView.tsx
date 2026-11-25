import { useEffect, useState } from "react"
import { toast } from "sonner"

import { api } from "@/api"
import type { Studio } from "@/App"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

export function StoryView({ studio }: { studio: Studio }) {
  const { state, refresh, track, busy } = studio
  const [text, setText] = useState(state.story)
  const dirty = text !== state.story
  useEffect(() => setText(state.story), [state.story])

  async function save() {
    await api.saveStory(text)
    toast.success("story.md saved")
    await refresh()
  }

  async function draft() {
    if (state.storyboard && !window.confirm("Redraft the storyboard from this story? Hand edits to scenes are replaced (the old storyboard is backed up).")) return
    if (dirty) await api.saveStory(text)
    await track(api.run("script", { force: true }))
  }

  return (
    <div className="mx-auto max-w-3xl px-5 py-10 md:px-10">
      <div className="mb-1 font-mono text-[11px] tracking-widest text-subtle uppercase">story.md</div>
      <h1 className="mb-2 text-3xl font-semibold tracking-tight">{state.storyboard?.title ?? "Your story"}</h1>
      <p className="mb-6 text-muted-foreground">
        Settings between the <code className="font-mono">---</code> lines, then the story in any language. The script stage turns it into scenes.
      </p>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        className="min-h-[460px] font-mono text-[13px] leading-6"
      />
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant="secondary" onClick={save} disabled={!dirty}>
          Save
        </Button>
        <Button onClick={draft} disabled={busy}>
          {state.storyboard ? "Redraft storyboard" : "Draft storyboard"}
        </Button>
        {dirty && <span className="text-[12px] text-warn">Unsaved changes</span>}
      </div>
      {state.storyboard && (
        <div className="mt-10 grid gap-3 sm:grid-cols-3">
          {(["who", "where", "feel"] as const).map((k) => (
            <div key={k} className="rounded-xl border bg-card p-4">
              <div className="mb-2 font-mono text-[11px] tracking-widest text-subtle uppercase">{k}</div>
              <p className="text-[13px] text-secondary-foreground">{state.storyboard!.audience[k]}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
