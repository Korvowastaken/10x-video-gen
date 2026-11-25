// The models picked for each task, and what work that runs them costs (pipeline/catalog.py).

import { useEffect, useState } from "react"

import type { LimitId } from "@/api"
import type { Studio } from "@/App"
import type { Cost } from "@/lib/progress"
import { modelsApi, taskCost, type Models } from "@/lib/providers"

/** Every task's model chain, looked up again whenever the studio state changes (a pick refreshes it). */
export function useModels(studio: Studio) {
  const [models, setModels] = useState<Models | null>(null)
  useEffect(() => {
    let live = true
    modelsApi
      .get()
      .then((m) => live && setModels(m))
      .catch(() => live && setModels(null))
    return () => {
      live = false
    }
  }, [studio.state])
  return [models, setModels] as const
}

/** The cost tag for work that runs these tasks, following the models picked for them (see taskCost). */
export function useTaskCost(studio: Studio, tasks: string[], limit: LimitId) {
  return useTaskCosts(studio, { work: [tasks, limit] }).work
}

/** Several cost tags from one lookup, e.g. { keyframe: [["image"], "pictures"], voice: [["tts"], "voices"] }. */
export function useTaskCosts<K extends string>(studio: Studio, specs: Record<K, [string[], LimitId]>): Record<K, Cost> {
  const [models] = useModels(studio)
  const out = {} as Record<K, Cost>
  for (const k of Object.keys(specs) as K[]) out[k] = taskCost(specs[k][0].map((t) => models?.tasks[t]), specs[k][1])
  return out
}
