import { ShieldCheck, UserRound } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { api, type Consent, type ConsentCharacter } from "@/api"
import type { Studio } from "@/App"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { Section, StatusDot } from "@/views/parts"

/**
 * The script's characters and whether each is a real person. A real person is drawn and voiced only
 * once their consent is confirmed here; the record is kept with the story (pipeline/consent.py).
 */
export function PeopleConsent({ studio }: { studio: Studio }) {
  const [data, setData] = useState<Consent | null>(null)
  const [asking, setAsking] = useState<ConsentCharacter | null>(null)
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

  async function act(work: Promise<Consent>, done: string) {
    try {
      setData(await work)
      toast.success(done)
      await studio.refresh()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  if (!data?.characters.length) return null
  const waiting = data.characters.filter((c) => c.status === "needs consent" || c.status === "withdrawn").length
  return (
    <Section
      title="People"
      aside={
        <span className={cn("text-[12px]", waiting ? "text-warn" : "text-subtle")}>
          {waiting
            ? `${waiting} real ${waiting === 1 ? "person needs" : "people need"} consent before anything of them is made`
            : "Mark anyone who is a real person: they are drawn and voiced only once they agree"}
        </span>
      }
      className="mt-0 mb-8"
    >
      <div className="divide-y border-y">
        {data.characters.map((c) => {
          const rec = data.records.find((r) => r.id === c.consent)
          return (
            <div key={c.id} className="flex items-center gap-4 py-2.5">
              <UserRound className="size-4 shrink-0 text-subtle" />
              <div className="w-56 min-w-0">
                <div className="truncate text-[13.5px] font-medium">{c.name}</div>
                <div className="text-[12px] text-subtle">
                  {c.visible ? "On screen" : "Voice only"} · {c.lines.length} line{c.lines.length === 1 ? "" : "s"}
                </div>
              </div>
              <div className="min-w-0 flex-1 text-[12.5px]">
                {c.status === "fictional" && <span className="text-subtle">Fictional</span>}
                {c.status === "agreed" &&
                  (c.lines_changed ? (
                    <StatusDot status="stale">Lines changed since they agreed: play them the new lines and confirm again</StatusDot>
                  ) : (
                    <StatusDot status="ok">
                      Real person · consent confirmed
                      {rec ? ` ${rec.date}${rec.self ? " (it's you)" : `, ${rec.how}`}` : ""}
                    </StatusDot>
                  ))}
                {c.status === "needs consent" && <StatusDot status="stale">Real person · nothing of them is made until they agree</StatusDot>}
                {c.status === "withdrawn" && (
                  <StatusDot status="stale">Consent withdrawn{rec?.withdrawn ? ` ${rec.withdrawn}` : ""} · nothing of them is made</StatusDot>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {c.status === "fictional" && (
                  <Button size="sm" variant="ghost" className="text-subtle" onClick={() => setAsking(c)}>
                    This is a real person
                  </Button>
                )}
                {(c.status === "needs consent" || c.status === "withdrawn" || c.lines_changed) && (
                  <Button size="sm" variant="secondary" onClick={() => setAsking(c)}>
                    <ShieldCheck /> {c.status === "needs consent" ? "Confirm consent" : "Confirm again"}
                  </Button>
                )}
                {c.status === "agreed" && c.consent && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-subtle"
                    onClick={() => act(api.withdrawConsent(c.consent!), `${c.name}'s consent withdrawn`)}
                  >
                    Withdraw
                  </Button>
                )}
                {(c.status === "needs consent" || c.status === "withdrawn") && c.consent && (
                  <Button size="sm" variant="ghost" className="text-subtle" onClick={() => act(api.notRealPerson(c.consent!), `${c.name} is fictional`)}>
                    Not a real person
                  </Button>
                )}
              </div>
            </div>
          )
        })}
      </div>
      {asking && (
        <ConsentDialog
          character={asking}
          wording={data.wording}
          onClose={() => setAsking(null)}
          onConfirm={async (body) => {
            await act(api.confirmConsent({ character: asking.id, ...body }), `${asking.name}'s consent is recorded`)
            setAsking(null)
          }}
        />
      )}
    </Section>
  )
}

type Answers = {
  self: boolean
  read_out: boolean
  agreed: boolean
  recording_kept: boolean
  how: string
  evidence: string
}

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
  const [a, setA] = useState<Answers>({
    self: false,
    read_out: false,
    agreed: false,
    recording_kept: false,
    how: "",
    evidence: "",
  })
  const [lang, setLang] = useState(0)
  const [saving, setSaving] = useState(false)
  const set = (patch: Partial<Answers>) => setA((x) => ({ ...x, ...patch }))
  const ready = a.self || (a.read_out && a.agreed && a.recording_kept && a.how.trim().length > 0)
  const name = character.name
  const block = wording[lang]

  async function confirm() {
    setSaving(true)
    await onConfirm(a)
    setSaving(false)
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[calc(100vh-48px)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Confirm {name}'s consent</DialogTitle>
          <DialogDescription>
            {name} is {character.visible ? "shown as an AI-made animated character" : "not shown (voice only)"}
            {character.lines.length ? `, and a computer voice${character.voice ? ` (${character.voice})` : ""} says their lines` : ""}. Nothing of a real person
            is drawn or voiced until they agree.
          </DialogDescription>
        </DialogHeader>

        <label className="flex items-center gap-2.5 rounded-md border px-3 py-2.5 text-[13px]">
          <Checkbox checked={a.self} onCheckedChange={(on) => set({ self: !!on })} />
          <span>
            This is me. <span className="text-subtle">I agree to appear and be voiced in this film myself.</span>
          </span>
        </label>

        {!a.self && block && (
          <div>
            <div className="mb-1.5 flex items-center gap-2">
              <span className="text-[12.5px] font-medium">Read this to {name}</span>
              {wording.length > 1 && (
                <span className="ml-auto flex gap-1">
                  {wording.map((w, i) => (
                    <button
                      key={w.label}
                      onClick={() => setLang(i)}
                      className={cn("rounded px-1.5 py-0.5 text-[12px] text-subtle hover:text-foreground", i === lang && "bg-secondary text-foreground")}
                    >
                      {w.label}
                    </button>
                  ))}
                </span>
              )}
            </div>
            <blockquote className="rounded-md bg-muted/60 px-3.5 py-3 text-[13px] leading-6">{block.text}</blockquote>
            {block.note && <p className="mt-1 text-[11.5px] text-subtle">{block.note}</p>}
          </div>
        )}

        {character.lines.length > 0 && (
          <div>
            <div className="mb-1.5 text-[12.5px] font-medium">{a.self ? "Your lines" : `Then play ${name} their lines`}</div>
            <ol className="max-h-44 divide-y overflow-y-auto rounded-md border text-[13px]">
              {character.lines.map((l, i) => (
                <li key={i} className="grid grid-cols-[36px_minmax(0,1fr)] gap-2 px-3 py-1.5">
                  <span className="text-[12px] text-subtle">{l.shot}</span>
                  <span>
                    <span className="block">{l.text}</span>
                    {l.en !== l.text && <span className="block text-[12px] text-muted-foreground">{l.en}</span>}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {!a.self && (
          <div className="space-y-2">
            <Tick checked={a.read_out} onChange={(on) => set({ read_out: on })}>
              I read this to {name}
              {character.lines.length ? " and played them their lines" : ""}
            </Tick>
            <Tick checked={a.agreed} onChange={(on) => set({ agreed: on })}>
              {name} said yes
            </Tick>
            <Tick checked={a.recording_kept} onChange={(on) => set({ recording_kept: on })}>
              I recorded their answer and keep the recording privately, not in this project
            </Tick>
            <div className="grid grid-cols-2 gap-3 pt-1">
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
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!ready || saving} onClick={confirm}>
            <ShieldCheck /> Confirm consent
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
