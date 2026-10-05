import type { TileJSON } from './api'

export type Selection = { kind: 'tract' | 'structure'; id: number } | null

// Vector tile layers the server publishes, each described by its TileJSON.
export const TILE_LAYERS = ['tracts', 'structures'] as const
export type TileLayerName = (typeof TILE_LAYERS)[number]
export type TileSources = Record<TileLayerName, TileJSON>

export interface LayerVisibility {
  tracts: boolean
  structures: boolean
  imagery: boolean
}
