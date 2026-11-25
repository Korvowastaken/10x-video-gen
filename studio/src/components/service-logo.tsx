import azure from "@lobehub/icons-static-svg/icons/azure-color.svg?raw"
import cerebras from "@lobehub/icons-static-svg/icons/cerebras-color.svg?raw"
import claude from "@lobehub/icons-static-svg/icons/claude-color.svg?raw"
import cloudflare from "@lobehub/icons-static-svg/icons/cloudflare-color.svg?raw"
import gemini from "@lobehub/icons-static-svg/icons/gemini-color.svg?raw"
import groq from "@lobehub/icons-static-svg/icons/groq.svg?raw"
import openrouter from "@lobehub/icons-static-svg/icons/openrouter.svg?raw"
import wavespeed from "@lobehub/icons-static-svg/icons/wavespeed.svg?raw"

import kaggle from "@/assets/kaggle.svg?raw"
import { cn } from "@/lib/utils"

/**
 * Each service's own mark: LobeHub's icon set (MIT) for the AI providers, and the "k" from
 * kaggle.com's logo for Kaggle. One-colour marks use currentColor, so they follow the ink in
 * light and dark. A service missing here falls back to its initials.
 */
const LOGOS: Record<string, string> = { anthropic: claude, azure, cerebras, cloudflare, gemini, groq, kaggle, openrouter, wavespeed }

/** A service's logo on a quiet tile; dimmed and greyed when it is not connected or paused. */
export function ServiceLogo({ id, label, size = 36, dim = false }: { id: string; label: string; size?: number; dim?: boolean }) {
  const svg = LOGOS[id]
  const letters = label.split(/\s+/).map((w) => w[0]).join("").slice(0, 2)
  return (
    <span
      aria-hidden
      style={{ width: size, height: size, fontSize: svg ? size * 0.55 : undefined }}
      className={cn(
        "grid shrink-0 place-items-center rounded-md border bg-background text-foreground transition-[filter,opacity] duration-150 [&_svg]:block",
        !svg && "text-[13px] font-semibold text-secondary-foreground",
        dim && "opacity-55 grayscale",
      )}
      {...(svg ? { dangerouslySetInnerHTML: { __html: svg } } : { children: letters })}
    />
  )
}
