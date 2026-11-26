/** The character a pipeline error says is held back for missing consent (storyboard.rule_errors), if any. */
export function heldForConsent(message: string): string | null {
  return /characters\/([\w-]+): portrays a real person but consent/.exec(message)?.[1] ?? null
}
