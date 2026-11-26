import { Check, ImagePlus, Trash2 } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { api, type Character, type Place, type Shot } from "@/api"
import type { Studio } from "@/App"
import { PeopleConsent } from "@/components/people-consent"
import { ProvidersPanel } from "@/components/providers-panel"
import { useTaskCost } from "@/lib/models"
import { RunButton } from "@/components/run-button"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import type { Cost } from "@/lib/progress"
import { cn } from "@/lib/utils"
import { ApproveBar, NextStep, NotYet, Page, StatusDot, StepHeader } from "@/views/parts"

const LEAD = "Every scene is drawn from the chosen sheet of each person and place. Add the photos you have, draw the sheets, pick one per person, then approve."

export function ReferencesView({ studio }: { studio: Studio }) {
  const { state, flow, track, busy, go } = studio
  const step = flow.steps.find((s) => s.id === "references")!
  const sb = state.storyboard
  const draw = useTaskCost(studio, ["image"], "pictures")
  if (!sb) return <NotYet studio={studio} step="references" n={3} title="References" lead={LEAD} needs="The sheets are drawn for the people and places the script names, so the script comes first." />
  const people = sb.characters.filter((c) => c.visible)
  const old = Object.values(state.sheets_stale ?? {}).filter(Boolean).length
  const undrawn = Object.values(state.sheets).filter((u) => u.some((x) => !x)).length
  return (
    <Page>
      <StepHeader
        n={3}
        title="References"
        lead={LEAD}
      >
        {(old > 0 || undrawn > 0) && (
          <StatusDot status="stale">{[undrawn && `${undrawn} not drawn`, old && `${old} out of date`].filter(Boolean).join(" · ")}</StatusDot>
        )}
        {state.limits?.pictures && !state.limits.pictures.used_up && state.limits.pictures.left != null && (
          <span className="text-[12px] text-subtle">~{state.limits.pictures.left} pictures left today</span>
        )}
        <RunButton cost={draw} disabled={busy || step.locked} onRun={() => track(api.drawSheets())}>
          {undrawn ? "Draw sheets" : "Redraw what changed"}
        </RunButton>
        {step.state === "approved" && <NextStep to="Film" onClick={() => go("film")} />}
      </StepHeader>
      <ProvidersPanel studio={studio} step="references" />
      <ApproveBar studio={studio} step="references" what="the references" />
      <PeopleConsent studio={studio} />

      <h2 className="mb-1 text-[13px] font-semibold">People</h2>
      <div className="divide-y border-y">
        {people.map((c) => (
          <Owner key={c.id} studio={studio} draw={draw} shots={sb.shots} id={c.id} name={c.name} sub={c.role} character={c} />
        ))}
      </div>
      <h2 className="mt-10 mb-1 text-[13px] font-semibold">Places</h2>
      <div className="divide-y border-y">
        {sb.locations.map((p) => (
          <Owner key={p.id} studio={studio} draw={draw} shots={sb.shots} id={p.id} name={p.name} place={p} />
        ))}
      </div>
    </Page>
  )
}

function Owner({ studio, draw, shots, id, name, sub, character, place }: { studio: Studio; draw: Cost; shots: Shot[]; id: string; name: string; sub?: string; character?: Character; place?: Place }) {
  const { state, refresh, track, busy, askConsent } = studio
  const input = useRef<HTMLInputElement>(null)
  const [text, setText] = useState(character?.look ?? place?.look ?? "")
  const [pending, setPending] = useState<File | null>(null)
  const [over, setOver] = useState(false)
  const sheets = state.sheets[id] ?? []
  const photo = state.photos[id]
  const chosen = character?.reference?.chosen ?? 0
  const scenes = shots.filter((s) => (character ? s.characters.includes(id) : s.location === id)).map((s) => s.id)
  const status = sheets.some((u) => !u) ? "missing" : state.sheets_stale?.[id] ? "stale" : "ok"

  function pick(file?: File) {
    if (!file) return
    if (character && !character.real_person) setPending(file)
    else upload(file)
  }

  async function upload(file: File) {
    try {
      await api.upload(id, file)
      toast.success(`Photo added to ${name}. Redraw to use it.`)
      await refresh()
      return true
    } catch (err) {
      toast.error((err as Error).message)
      return false
    }
  }

  /** The photo shows a real person: switch them on, add the photo, then ask for their consent. */
  async function addAsReal(file: File) {
    try {
      await api.markRealPerson(id)
    } catch (err) {
      return toast.error((err as Error).message)
    }
    if (await upload(file)) askConsent(id)
  }

  const saved = character?.look ?? place?.look ?? ""

  async function saveLook() {
    try {
      if (character) await api.saveCharacter({ ...character, look: text })
      else if (place) await api.savePlace({ ...place, look: text })
      else return
      toast.success(`${name}: look saved. Redraw to see it.`)
      await refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function choose(i: number) {
    if (!character?.reference || i === chosen) return
    await api.saveCharacter({ ...character, reference: { ...character.reference, chosen: i } })
    toast.success(`Sheet ${i + 1} approved. ${scenes.length} scene${scenes.length === 1 ? "" : "s"} with ${name} now need new stills.`)
    await refresh()
  }

  return (
    <section className="grid grid-cols-[132px_minmax(0,1fr)] gap-6 py-6">
      <div>
        <div
          onDragOver={(e) => (e.preventDefault(), setOver(true))}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => (e.preventDefault(), setOver(false), pick(e.dataTransfer.files[0]))}
          onClick={() => input.current?.click()}
          className={cn(
            "relative grid aspect-square cursor-pointer place-items-center overflow-hidden rounded-lg border border-dashed bg-muted/60 text-muted-foreground transition-colors hover:border-primary hover:text-foreground",
            over && "border-primary bg-accent",
            photo && "border-solid",
          )}
        >
          {photo ? (
            <img src={photo} alt={`Reference photo for ${name}`} className="size-full object-cover" />
          ) : (
            <div className="flex flex-col items-center gap-1.5 px-3 text-center text-[12px]">
              <ImagePlus className="size-4" />
              Drop a photo
            </div>
          )}
          <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => pick(e.target.files?.[0])} />
        </div>
        {photo && (
          <Button variant="ghost" size="xs" className="mt-1.5 text-subtle" onClick={async () => (await api.removePhoto(id), refresh())}>
            <Trash2 /> Remove photo
          </Button>
        )}
      </div>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <span className="font-medium">{name}</span>
            {status === "ok" && <StatusDot status="ok">Up to date</StatusDot>}
            {status === "stale" && <StatusDot status="stale">Out of date, redraw</StatusDot>}
            {status === "missing" && <StatusDot status="missing">Not drawn yet</StatusDot>}
          </div>
          <div className="mt-0.5 mb-3 text-[12px] text-subtle">
            {sub && <span className="capitalize">{sub} · </span>}
            In {scenes.length ? scenes.join(", ") : "no scene"}
            {character?.real_person && <span className="ml-2 text-warn">Real person</span>}
          </div>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={place ? "Describe the place: time of day, light, colours, key objects" : "Describe how they look"}
            className="min-h-20 text-[13px]"
          />
          {text !== saved && (
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={saveLook}>
                Save look
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setText(saved)}>
                Discard
              </Button>
            </div>
          )}
        </div>

        <div>
          <div className="mb-1.5 text-[12px] text-subtle">{character && sheets.length > 1 ? "Pick the sheet every scene copies" : "Sheet"}</div>
          <div className="flex gap-2">
            {sheets.map((url, i) => {
              const on = !!character && i === chosen
              return url ? (
                <button
                  key={i}
                  onClick={() => choose(i)}
                  disabled={!character}
                  className={cn(
                    "relative w-[84px] overflow-hidden rounded-md ring-1 ring-border transition-shadow",
                    character && "hover:ring-foreground/40",
                    on && "ring-2 ring-primary hover:ring-primary",
                  )}
                  title={character ? (on ? "Approved" : "Approve this sheet") : undefined}
                >
                  <img src={url} alt={`${name}, sheet ${i + 1}`} className={cn("w-full object-cover", character ? "aspect-[3/4]" : "aspect-[9/16]")} />
                  {on && (
                    <span className="absolute top-1 right-1 grid size-4 place-items-center rounded-full bg-primary text-white">
                      <Check className="size-2.5" strokeWidth={3} />
                    </span>
                  )}
                </button>
              ) : (
                <div key={i} className="grid aspect-[3/4] w-[84px] place-items-center rounded-md border border-dashed text-[11px] text-subtle">
                  Not drawn
                </div>
              )
            })}
          </div>
          {character && sheets.every(Boolean) && (
            <RunButton
              size="sm"
              variant="ghost"
              className="mt-1.5 text-subtle"
              cost={draw}
              disabled={busy}
              onRun={async () => {
                await api.anotherSheet(id)
                await track(api.drawSheets())
              }}
            >
              Draw another
            </RunButton>
          )}
        </div>
      </div>

      <AlertDialog open={!!pending} onOpenChange={(o) => !o && setPending(null)}>
        <AlertDialogContent className="data-[size=default]:sm:max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Is this a photo of a real person?</AlertDialogTitle>
            <AlertDialogDescription>
              {name} is a made-up character. If the photo shows someone real, {name} becomes a real person, and nothing of them is drawn
              or voiced until they agree.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <Button
              variant="secondary"
              onClick={() => {
                if (pending) upload(pending)
                setPending(null)
              }}
            >
              No, add it
            </Button>
            <Button
              onClick={() => {
                if (pending) addAsReal(pending)
                setPending(null)
              }}
            >
              Yes, ask their consent
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
