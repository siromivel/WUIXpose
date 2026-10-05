export type Selection = { kind: 'tract' | 'structure'; id: number } | null

export interface LayerVisibility {
  tracts: boolean
  structures: boolean
  imagery: boolean
}

// Keep in step with min_zoom in src/wuixpose/core/tiles.py; below these the server sends nothing.
export const MIN_ZOOM = { tracts: 12, structures: 13 } as const
