import { useState } from "react"

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
import { cn } from "@/lib/utils"
import { usd, type Cost } from "@/lib/progress"

/** "Free" in green or the price in orange, so the cost is read before the click. */
export function CostTag({ cost, className }: { cost: Cost; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-[18px] items-center rounded-[4px] px-1.5 text-[11px] font-medium tabular-nums",
        cost.paid ? "bg-paid/15 text-paid" : "bg-free/12 text-free",
        className,
      )}
    >
      {cost.paid ? usd(cost.usd) : "Free"}
    </span>
  )
}

type Confirm = { title: string; body: React.ReactNode; action: string }

/**
 * A button that runs work. Paid work always asks first, with the price and what was spent so far.
 * Free work runs at once, unless `confirm` is given (for free but destructive work, like a redraft).
 */
export function RunButton({
  cost,
  onRun,
  children,
  spent,
  what,
  confirm,
  variant,
  size,
  disabled,
  className,
}: {
  cost: Cost
  onRun: () => unknown
  children: React.ReactNode
  /** Spent so far at WaveSpeed, shown in the paid confirm. */
  spent?: number
  /** What the money buys, in words, for the paid confirm. */
  what?: string
  confirm?: Confirm
  variant?: "default" | "secondary" | "outline" | "ghost"
  size?: "default" | "sm" | "lg"
  disabled?: boolean
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const ask = cost.paid || confirm
  return (
    <>
      <Button
        variant={variant ?? (cost.paid ? "outline" : "default")}
        size={size}
        disabled={disabled}
        className={cn(cost.paid && !variant && "border-paid/40 text-paid hover:bg-paid/10 hover:text-paid", className)}
        onClick={() => (ask ? setOpen(true) : onRun())}
      >
        {children}
        <CostTag cost={cost} className={cn("-mr-1", !cost.paid && (variant ?? "default") === "default" && "bg-white/15 text-white")} />
      </Button>
      {ask && (
        <AlertDialog open={open} onOpenChange={setOpen}>
          <AlertDialogContent className="data-[size=default]:sm:max-w-md">
            <AlertDialogHeader>
              <AlertDialogTitle>{cost.paid ? `Spend ${usd(cost.usd)} at ${cost.via}?` : confirm!.title}</AlertDialogTitle>
              <AlertDialogDescription render={<div />} className="space-y-2">
                {cost.paid ? (
                  <>
                    <p>{what ?? "This buys generated media."} It is charged to your {cost.via} balance and cannot be undone.</p>
                    {spent != null && (
                      <p className="text-subtle">
                        Spent so far: {usd(spent)}. After this: {usd(spent + cost.usd)}.
                      </p>
                    )}
                  </>
                ) : (
                  confirm!.body
                )}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <Button
                className={cn(cost.paid && "bg-paid text-white hover:bg-paid/85")}
                onClick={() => {
                  setOpen(false)
                  onRun()
                }}
              >
                {cost.paid ? `${confirm?.action ?? "Buy"} for ${usd(cost.usd)}` : confirm!.action}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </>
  )
}
