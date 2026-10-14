import type { TileJSON } from './api'

export type Selection = { kind: 'tract' | 'structure'; id: number } | null

// Vector tile layers the server publishes, each described by its TileJSON.
export const TILE_LAYERS = ['tracts', 'zones', 'structures'] as const
export type TileLayerName = (typeof TILE_LAYERS)[number]
export type TileSources = Record<TileLayerName, TileJSON>

export interface LayerVisibility {
  tracts: boolean
  structures: boolean
  zones: boolean
  imagery: boolean
}

// How the rings in zone tiles are shown, nearest the structure first. Keys are the server's
// (RINGS in src/wuixpose/core/zones.py); a ring not listed here draws in ZONE_FALLBACK_COLOR.
export const ZONE_RINGS = [
  { key: 'hiz_0_5', label: 'Zone 1', range: '0–5 ft', color: '#c1121f' },
  { key: 'hiz_5_30', label: 'Zone 2', range: '5–30 ft', color: '#f4a100' },
  { key: 'hiz_30_100', label: 'Zone 3', range: '30–100 ft', color: '#2a9d8f' },
] as const
export const ZONE_FALLBACK_COLOR = '#6b7280'
