import { createContext, useContext } from "react"

import type { State } from "@/api"
import { blocked, type Cost } from "@/lib/progress"

/** Today's free limits, from /api/state, for any button that shows a cost. */
export const LimitsContext = createContext<State["limits"]>(undefined)

/** The used-up limit this work would hit, or null when it can run now. */
export function useBlocked(cost: Cost) {
  return blocked(cost, useContext(LimitsContext))
}
