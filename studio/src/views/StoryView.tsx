import { AlertTriangle } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { api } from "@/api"
import type { Studio } from "@/App"
import { RunButton } from "@/components/run-button"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { FREE } from "@/lib/progress"
import { Page, StepHeader } from "@/views/parts"

export function StoryView({ studio }: { studio: Studio }) {
  const { state, refresh, track, busy, go } = studio
  const sb = state.storyboard
  const [text, setText] = useState(state.story)
  const dirty = text !== state.story
  useEffect(() => setText(state.story), [state.story])

  async function save() {
    await api.saveStory(text)
    toast.success("Story saved")
    await refresh()
  }

  async function draft() {
    if (dirty) await api.saveStory(text)
    await track(api.run("script", { force: true }))
  }

  return (
    <Page>
      <StepHeader n={1} title="Story" lead="Write the family story in any language. Gemini turns it into scenes, lines and pictures." />
      <div className="grid grid-cols-[minmax(0,1fr)_280px] gap-8">
        <div>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            className="min-h-[calc(100vh-260px)] font-mono text-[13px] leading-6"
          />
          <p className="mt-2 text-[12px] text-subtle">
            Settings go between the <code className="font-mono">---</code> lines at the top (language, look, length). The story follows.
          </p>
        </div>
        <aside className="space-y-6">
          {sb && state.story_changed && !dirty && (
            <div className="flex gap-2.5 rounded-lg border border-warn/30 bg-warn/8 p-3 text-[13px]">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
              <span>The story changed since the scenes were drafted. Redraft to bring the changes in.</span>
            </div>
          )}
          <div className="space-y-2">
            {dirty && (
              <Button variant="secondary" className="w-full" onClick={save}>
                Save story
              </Button>
            )}
            <RunButton
              className="w-full"
              cost={FREE("Gemini", "writing")}
              disabled={busy || !text.trim()}
              onRun={draft}
              confirm={
                sb
                  ? {
                      title: "Redraft every scene?",
                      body: "Gemini writes the scenes again from the story. Edits you made to scenes are replaced. The old storyboard is kept as a backup in outputs/script.",
                      action: "Redraft",
                    }
                  : undefined
              }
            >
              {sb ? "Redraft scenes" : "Draft scenes"}
            </RunButton>
            {sb && (
              <Button variant="ghost" className="w-full" onClick={() => go("references")}>
                Go to Look
              </Button>
            )}
          </div>
          {sb && (
            <dl className="space-y-4 border-t pt-5">
              <div>
                <dt className="text-[12px] text-subtle">Logline</dt>
                <dd className="mt-0.5 text-[13px] text-secondary-foreground">{sb.logline}</dd>
              </div>
              {(["who", "where", "feel"] as const).map((k) => (
                <div key={k}>
                  <dt className="text-[12px] text-subtle">{k === "who" ? "Who watches" : k === "where" ? "Where" : "How it should feel"}</dt>
                  <dd className="mt-0.5 text-[13px] text-secondary-foreground">{sb.audience[k]}</dd>
                </div>
              ))}
            </dl>
          )}
        </aside>
      </div>
    </Page>
  )
}
