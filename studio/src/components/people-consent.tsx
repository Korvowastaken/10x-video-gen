import { Check, ShieldCheck } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { api, type Consent, type ConsentCharacter, type ConsentRecord } from "@/api"
import type { Studio } from "@/App"
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
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import { Section } from "@/views/parts"

/** "2026-11-26" → "26 Nov". */
const day = (iso?: string) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "")

/** Where a character stands, as one tone: made-up, agreed, or held back until someone acts. */
const toneOf = (c: ConsentCharacter) => (c.status === "fictional" ? "off" : c.status === "agreed" && !c.lines_changed ? "ok" : "held")

/**
 * The consent popup for one character, opened from anywhere through `studio.askConsent`: the People
 * list, a photo of a real person, or a run that stopped because their consent is missing.
 */
export function ConsentHost({ character, onClose, onDone }: { character: string | null; onClose: () => void; onDone: () => Promise<void> }) {
  const [data, setData] = useState<Consent | null>(null)
  useEffect(() => {
    if (!character) return
    let live = true
    api
      .consent()
      .then((d) => live && setData(d))
      .catch((err) => {
        toast.error((err as Error).message)
        onClose()
      })
    return () => {
      live = false
    }
  }, [character, onClose])
  const c = character ? data?.characters.find((x) => x.id === character) : undefined
  if (!c || !data) return null
  return (
    <ConsentDialog
      key={c.id}
      character={c}
      wording={data.wording}
      onClose={onClose}
      onConfirm={async (body) => {
        try {
          await api.confirmConsent({ character: c.id, ...body })
          toast.success(`${c.name}'s consent is recorded`)
          onClose()
          await onDone()
        } catch (err) {
          toast.error((err as Error).message)
        }
      }}
    />
  )
}

/**
 * The script's characters, each with a Real person switch. A real person is drawn and voiced only once
 * their consent is confirmed; the record is kept with the story (pipeline/consent.py).
 */
export function PeopleConsent({ studio }: { studio: Studio }) {
  const [data, setData] = useState<Consent | null>(null)
  const [unmarking, setUnmarking] = useState<ConsentCharacter | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    api
      .consent()
      .then((d) => live && setData(d))
      .catch(() => live && setData(null))
    return () => {
      live = false
    }
  }, [studio.state])

  async function act(id: string, work: Promise<Consent>, done?: string) {
    setPending(id)
    try {
      const next = await work
      setData(next)
      if (done) toast.success(done)
      await studio.refresh()
      return next
    } catch (err) {
      toast.error((err as Error).message)
      return null
    } finally {
      setPending(null)
    }
  }

  async function toggle(c: ConsentCharacter, on: boolean) {
    if (!on) return setUnmarking(c)
    // Protected at once; the confirmation follows. Cancelling it leaves them protected.
    const next = await act(c.id, api.markRealPerson(c.id))
    if (next?.characters.some((x) => x.id === c.id && x.status !== "agreed")) studio.askConsent(c.id)
  }

  if (!data?.characters.length) return null
  const held = data.characters.filter((c) => toneOf(c) === "held").length
  return (
    <Section
      title="Real people"
      aside={
        <span className={cn("text-[12px]", held ? "text-warn" : "text-subtle")}>
          {held
            ? `${held} ${held === 1 ? "person is" : "people are"} held back until consent is confirmed`
            : "Switch on anyone who is a real person. They are drawn and voiced only once they agree."}
        </span>
      }
      className="mt-0 mb-8"
    >
      <div role="table" aria-label="People in the film" className="border-y text-[13px]">
        <div role="row" className="grid grid-cols-[minmax(0,1fr)_152px_minmax(0,1.7fr)] gap-6 border-b py-2 text-[12px] text-subtle">
          <span role="columnheader">Person</span>
          <span role="columnheader">Real person</span>
          <span role="columnheader">Consent</span>
        </div>
        <div className="divide-y">
          {data.characters.map((c) => (
            <PersonRow
              key={c.id}
              c={c}
              record={data.records.find((r) => r.id === c.consent)}
              busy={pending === c.id}
              onToggle={(on) => toggle(c, on)}
              onAsk={() => studio.askConsent(c.id)}
              onWithdraw={() => c.consent && act(c.id, api.withdrawConsent(c.consent), `${c.name}'s consent is withdrawn`)}
            />
          ))}
        </div>
      </div>

      <AlertDialog open={!!unmarking} onOpenChange={(o) => !o && setUnmarking(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Make {unmarking?.name} a made-up character?</AlertDialogTitle>
            <AlertDialogDescription>
              {unmarking?.name} will be drawn and voiced as a fictional character, with no consent asked.
              {unmarking?.status === "agreed" || unmarking?.status === "withdrawn" ? " Their consent record is kept." : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep as a real person</AlertDialogCancel>
            <Button
              onClick={() => {
                const c = unmarking!
                setUnmarking(null)
                if (c.consent) act(c.id, api.notRealPerson(c.consent), `${c.name} is now a made-up character`)
              }}
            >
              Make fictional
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Section>
  )
}

function PersonRow({
  c,
  record,
  busy,
  onToggle,
  onAsk,
  onWithdraw,
}: {
  c: ConsentCharacter
  record?: ConsentRecord
  busy: boolean
  onToggle: (on: boolean) => void
  onAsk: () => void
  onWithdraw: () => void
}) {
  const tone = toneOf(c)
  const lines = c.lines.length ? `${c.lines.length} line${c.lines.length === 1 ? "" : "s"}` : "no lines"
  return (
    <div role="row" className="grid min-h-14 grid-cols-[minmax(0,1fr)_152px_minmax(0,1.7fr)] items-center gap-6 py-2.5">
      <div role="cell" className="flex min-w-0 items-center gap-3">
        <span
          aria-hidden
          className={cn(
            "grid size-8 shrink-0 place-items-center rounded-full text-[12.5px] font-semibold transition-colors duration-200",
            tone === "off" && "border border-thread text-subtle",
            tone === "ok" && "bg-free/12 text-free",
            tone === "held" && "bg-warn/10 text-warn",
          )}
        >
          {c.name.trim().charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium">{c.name}</span>
          <span className="block text-[12px] text-subtle">
            {c.visible ? "On screen" : "Voice only"} · {lines}
          </span>
        </span>
      </div>

      <label role="cell" className="flex w-fit cursor-pointer items-center gap-2.5">
        <Switch checked={c.real_person} disabled={busy} onCheckedChange={onToggle} aria-label={`${c.name} is a real person`} />
        <span className={cn("text-[12.5px]", c.real_person ? "text-foreground" : "text-subtle")}>{c.real_person ? "Real person" : "Made up"}</span>
      </label>

      <div role="cell" className="flex min-w-0 items-center justify-between gap-4">
        <ConsentState c={c} record={record} />
        {(c.status === "needs consent" || c.status === "withdrawn" || c.lines_changed) && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={onAsk} className="shrink-0">
            <ShieldCheck /> {c.status === "needs consent" ? "Confirm consent" : "Confirm again"}
          </Button>
        )}
        {c.status === "agreed" && !c.lines_changed && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={onWithdraw} className="shrink-0 text-subtle">
            Withdraw
          </Button>
        )}
      </div>
    </div>
  )
}

function ConsentState({ c, record }: { c: ConsentCharacter; record?: ConsentRecord }) {
  if (c.status === "fictional") return <span className="text-[12.5px] text-subtle">Not needed for a made-up character</span>
  if (c.status === "agreed" && !c.lines_changed)
    return (
      <span className="flex min-w-0 items-center gap-2">
        <Check className="size-3.5 shrink-0 text-free" strokeWidth={2.5} />
        <span className="truncate">
          {record?.self ? "It's you" : "Agreed"}
          {record && <span className="text-muted-foreground"> · {day(record.date)}{!record.self && record.how ? ` · ${record.how}` : ""}</span>}
        </span>
      </span>
    )
  const text =
    c.status === "withdrawn"
      ? `Withdrawn ${day(record?.withdrawn)}. Nothing of them is made.`
      : c.lines_changed
        ? "Their lines changed since they agreed. Play them the new ones."
        : "Not confirmed yet. Nothing of them is made."
  return (
    <span className="flex min-w-0 items-center gap-2 text-warn">
      <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-warn" />
      <span className="truncate" title={text}>
        {text}
      </span>
    </span>
  )
}

type Answers = { self: boolean; read_out: boolean; agreed: boolean; recording_kept: boolean; how: string; evidence: string }

function ConsentDialog({
  character,
  wording,
  onClose,
  onConfirm,
}: {
  character: ConsentCharacter
  wording: Consent["wording"]
  onClose: () => void
  onConfirm: (answers: Answers) => Promise<void>
}) {
  const [a, setA] = useState<Answers>({ self: false, read_out: false, agreed: false, recording_kept: false, how: "", evidence: "" })
  const [lang, setLang] = useState(0)
  const [saving, setSaving] = useState(false)
  const set = (patch: Partial<Answers>) => setA((x) => ({ ...x, ...patch }))
  const name = character.name
  const block = wording[lang]
  const hasLines = character.lines.length > 0
  const ticks = [a.read_out, a.agreed, a.recording_kept].filter(Boolean).length
  const ready = a.self || (ticks === 3 && a.how.trim().length > 0)
  const left = a.self ? "" : ticks < 3 ? `${3 - ticks} left to tick` : !a.how.trim() ? "Say how it was recorded" : ""
  const again = character.status === "withdrawn" || character.lines_changed
  const shown = character.visible ? "drawn as an animated character" : "heard, not shown"
  const voiced = hasLines ? `, and a computer voice${character.voice ? ` (${character.voice})` : ""} says their lines` : ""

  async function confirm() {
    setSaving(true)
    await onConfirm(a)
    setSaving(false)
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[calc(100vh-48px)] gap-5 overflow-y-auto sm:max-w-xl">
        <DialogHeader className="flex-row items-start gap-3.5 space-y-0">
          <span aria-hidden className="grid size-10 shrink-0 place-items-center rounded-full bg-warn/10 text-[15px] font-semibold text-warn">
            {name.trim().charAt(0).toUpperCase()}
          </span>
          <span className="min-w-0 space-y-1">
            <DialogTitle className="text-balance">{again ? `Ask ${name} again` : `Did ${name} agree to be in the film?`}</DialogTitle>
            <DialogDescription className="text-pretty">
              {character.lines_changed && character.status === "agreed" ? "Their lines changed since they agreed. " : ""}
              {name} is {shown}
              {voiced}. Until they agree, nothing of them is made.
            </DialogDescription>
          </span>
        </DialogHeader>

        <label
          className={cn(
            "flex cursor-pointer items-center justify-between gap-4 rounded-md border px-3.5 py-3 transition-colors duration-150 hover:bg-muted/40",
            a.self && "border-free/40 bg-free/5 hover:bg-free/5",
          )}
        >
          <span>
            <span className="block text-[13px] font-medium">I am {name}</span>
            <span className="block text-[12px] text-subtle">You agree for yourself, so there is nothing to read out or record.</span>
          </span>
          <Switch checked={a.self} onCheckedChange={(on) => set({ self: on })} aria-label={`I am ${name}`} />
        </label>

        {!a.self && block && (
          <Stage n={1} title={`Read this to ${name}`}>
            {wording.length > 1 && (
              <span role="tablist" aria-label="Language" className="absolute top-0 right-0 flex rounded-md border p-0.5">
                {wording.map((w, i) => (
                  <button
                    key={w.label}
                    role="tab"
                    aria-selected={i === lang}
                    onClick={() => setLang(i)}
                    className={cn(
                      "rounded-[4px] px-2 py-0.5 text-[12px] text-subtle transition-colors duration-150 hover:text-foreground",
                      i === lang && "bg-secondary text-foreground",
                    )}
                  >
                    {w.label}
                  </button>
                ))}
              </span>
            )}
            <blockquote lang={block.label === "Amharic" ? "am" : undefined} className="rounded-md bg-muted/60 px-3.5 py-3 text-[13px] leading-6">
              {block.text}
            </blockquote>
            {block.note && <p className="mt-1.5 text-[11.5px] text-subtle">{block.note}</p>}
          </Stage>
        )}

        {hasLines && (
          <Stage n={a.self ? undefined : 2} title={a.self ? "Your lines" : `Play ${name} their lines`}>
            <ol className="max-h-44 divide-y overflow-y-auto rounded-md border text-[13px]">
              {character.lines.map((l, i) => (
                <li key={i} className="grid grid-cols-[36px_minmax(0,1fr)] gap-2 px-3 py-1.5">
                  <span className="pt-px text-[12px] text-subtle tabular-nums">{l.shot}</span>
                  <span>
                    <span lang="am" className="block">
                      {l.text}
                    </span>
                    {l.en !== l.text && <span className="block text-[12px] text-muted-foreground">{l.en}</span>}
                  </span>
                </li>
              ))}
            </ol>
          </Stage>
        )}

        {!a.self && (
          <Stage n={hasLines ? 3 : 2} title="Confirm what happened">
            <div className="space-y-2.5">
              <Tick checked={a.read_out} onChange={(on) => set({ read_out: on })}>
                I read this to {name}
                {hasLines ? " and played them their lines" : ""}
              </Tick>
              <Tick checked={a.agreed} onChange={(on) => set({ agreed: on })}>
                {name} said yes
              </Tick>
              <Tick checked={a.recording_kept} onChange={(on) => set({ recording_kept: on })}>
                I recorded their answer and keep it privately, outside this project
              </Tick>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-[12px] text-secondary-foreground">How was it recorded?</span>
                <Input value={a.how} onChange={(e) => set({ how: e.target.value })} placeholder="Voice note on my phone" />
              </label>
              <label className="block">
                <span className="mb-1 block text-[12px] text-secondary-foreground">
                  Where is it kept? <span className="text-subtle">Optional</span>
                </span>
                <Input value={a.evidence} onChange={(e) => set({ evidence: e.target.value })} placeholder="Phone, Voice Memos" />
              </label>
            </div>
          </Stage>
        )}

        <DialogFooter className="items-center sm:justify-between">
          <span aria-live="polite" className="text-[12px] text-subtle">
            {left}
          </span>
          <span className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Not now
            </Button>
            <Button disabled={!ready || saving} onClick={confirm}>
              <ShieldCheck /> {a.self ? "Confirm, it's me" : `${name} agreed`}
            </Button>
          </span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** One part of the consent popup, numbered where the order matters (read, play, then confirm). */
function Stage({ n, title, children }: { n?: number; title: string; children: React.ReactNode }) {
  return (
    <section className="relative">
      <h3 className="mb-2 flex h-6 items-center gap-2 text-[12.5px] font-medium">
        {n !== undefined && (
          <span aria-hidden className="grid size-5 place-items-center rounded-full border border-thread text-[11px] text-subtle tabular-nums">
            {n}
          </span>
        )}
        {title}
      </h3>
      {children}
    </section>
  )
}

function Tick({ checked, onChange, children }: { checked: boolean; onChange: (on: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-[13px]">
      <Checkbox className="mt-0.5" checked={checked} onCheckedChange={(on) => onChange(!!on)} />
      <span>{children}</span>
    </label>
  )
}
