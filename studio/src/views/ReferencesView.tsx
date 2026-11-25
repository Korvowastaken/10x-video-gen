import { ImagePlus, Trash2 } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { api, type Character } from "@/api"
import type { Studio } from "@/App"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

export function ReferencesView({ studio }: { studio: Studio }) {
  const { state, track, busy } = studio
  const sb = state.storyboard
  if (!sb) return <Empty />
  const people = sb.characters.filter((c) => c.visible)
  return (
    <div className="mx-auto max-w-5xl px-5 py-10 md:px-10">
      <div className="mb-1 font-mono text-[11px] tracking-widest text-subtle uppercase">Look</div>
      <h1 className="mb-2 text-3xl font-semibold tracking-tight">References</h1>
      <p className="mb-8 max-w-2xl text-muted-foreground">
        Upload a photo to steer a character or place. Every keyframe is drawn from the approved sheet, so fix the look here first.
      </p>
      <div className="grid gap-4">
        {people.map((c) => (
          <Owner key={c.id} studio={studio} id={c.id} name={c.name} character={c} />
        ))}
        {sb.locations.map((p) => (
          <Owner key={p.id} studio={studio} id={p.id} name={p.name} look={p.look} />
        ))}
      </div>
      <div className="mt-8">
        <Button onClick={() => track(api.run("keyframes"))} disabled={busy}>
          Draw sheets and keyframes
        </Button>
        <span className="ml-3 text-[12px] text-subtle">Free (Cloudflare allowance). Only what changed is redrawn.</span>
      </div>
    </div>
  )
}

function Owner({ studio, id, name, character, look }: { studio: Studio; id: string; name: string; character?: Character; look?: string }) {
  const { state, refresh } = studio
  const input = useRef<HTMLInputElement>(null)
  const [text, setText] = useState(character?.look ?? look ?? "")
  const sheets = state.sheets[id] ?? []
  const photo = state.photos[id]
  const chosen = character?.reference?.chosen ?? 0

  async function upload(file?: File) {
    if (!file) return
    if (character?.real_person === false && !window.confirm(`Is this a photo of a real person? If so, record their consent in ETHICS.md and mark ${name} as a real person first.`)) return
    try {
      await api.upload(id, file)
      toast.success("Photo added. Redraw to use it.")
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function saveLook() {
    if (!character) return
    try {
      await api.saveCharacter({ ...character, look: text })
      toast.success(`${name}: look saved`)
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function choose(i: number) {
    if (!character?.reference) return
    await api.saveCharacter({ ...character, reference: { ...character.reference, chosen: i } })
    await refresh()
  }

  return (
    <section className="grid gap-4 rounded-xl border bg-card p-4 md:grid-cols-[200px_minmax(0,1fr)]">
      <div>
        <div className="mb-1 font-medium">{name}</div>
        <div className="mb-3 font-mono text-[11px] text-subtle">
          {id}
          {character?.real_person && <span className="ml-2 text-warn">real person · {character.consent}</span>}
        </div>
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => (e.preventDefault(), upload(e.dataTransfer.files[0]))}
          onClick={() => input.current?.click()}
          className="relative grid aspect-square cursor-pointer place-items-center overflow-hidden rounded-lg border border-dashed bg-muted text-muted-foreground transition-colors hover:border-primary"
        >
          {photo ? (
            <img src={photo} alt={`Reference for ${name}`} className="size-full object-cover" />
          ) : (
            <div className="flex flex-col items-center gap-2 text-[12px]">
              <ImagePlus className="size-5" />
              Drop or pick a photo
            </div>
          )}
          <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => upload(e.target.files?.[0])} />
        </div>
        {photo && (
          <Button variant="ghost" size="sm" className="mt-2" onClick={async () => (await api.removePhoto(id), refresh())}>
            <Trash2 /> Remove photo
          </Button>
        )}
      </div>
      <div className="min-w-0">
        <Textarea value={text} onChange={(e) => setText(e.target.value)} disabled={!character} className="min-h-20 text-[13px]" />
        {character && (
          <Button variant="secondary" size="sm" className="mt-2" onClick={saveLook} disabled={text === character.look}>
            Save look
          </Button>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {sheets.map((url, i) =>
            url ? (
              <button
                key={i}
                onClick={() => choose(i)}
                disabled={!character}
                className={cn("w-24 overflow-hidden rounded-lg border-2 border-transparent transition-colors", character && i === chosen && "border-primary")}
                title={character ? (i === chosen ? "Approved sheet" : "Approve this sheet") : undefined}
              >
                <img src={url} alt={`${name} sheet ${i + 1}`} className="aspect-[3/4] w-full object-cover" />
              </button>
            ) : (
              <div key={i} className="grid aspect-[3/4] w-24 place-items-center rounded-lg bg-muted text-[11px] text-subtle">not drawn</div>
            ),
          )}
        </div>
      </div>
    </section>
  )
}

function Empty() {
  return <div className="p-10 text-muted-foreground">Draft the storyboard from your story first.</div>
}
