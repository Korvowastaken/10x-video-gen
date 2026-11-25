import { Slider as SliderPrimitive } from "@base-ui/react/slider"
import { cn } from "@/lib/utils"

/**
 * shadcn's Base UI slider on the studio's tokens. With `mark`, the track shows a tick at that
 * value (the neutral point) and no fill, for settings that go both ways from "as recorded".
 */
function Slider({
  className,
  defaultValue,
  value,
  min = 0,
  max = 100,
  mark,
  "aria-label": label,
  ...props
}: SliderPrimitive.Root.Props & { mark?: number; "aria-label"?: string }) {
  const _values = Array.isArray(value)
    ? value
    : Array.isArray(defaultValue)
      ? defaultValue
      : [min, max]

  return (
    <SliderPrimitive.Root
      className={cn("data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full", className)}
      data-slot="slider"
      defaultValue={defaultValue}
      value={value}
      min={min}
      max={max}
      thumbAlignment="edge"
      {...props}
    >
      <SliderPrimitive.Control className="relative flex h-5 w-full touch-none items-center select-none data-disabled:opacity-50">
        <SliderPrimitive.Track data-slot="slider-track" className="relative h-[3px] w-full grow rounded-full bg-input select-none">
          {mark == null ? (
            <SliderPrimitive.Indicator data-slot="slider-range" className="h-full rounded-full bg-foreground select-none" />
          ) : (
            <span
              aria-hidden
              className="absolute top-1/2 h-2.5 w-px -translate-y-1/2 bg-subtle"
              style={{ left: `${((mark - min) / (max - min)) * 100}%` }}
            />
          )}
        </SliderPrimitive.Track>
        {Array.from({ length: _values.length }, (_, index) => (
          <SliderPrimitive.Thumb
            data-slot="slider-thumb"
            key={index}
            aria-label={label}
            className="relative block size-3.5 shrink-0 rounded-full border border-foreground/70 bg-background shadow-sm ring-ring/40 transition-[box-shadow] select-none after:absolute after:-inset-2 hover:ring-3 focus-visible:ring-3 focus-visible:outline-hidden active:ring-3"
          />
        ))}
      </SliderPrimitive.Control>
    </SliderPrimitive.Root>
  )
}

export { Slider }
