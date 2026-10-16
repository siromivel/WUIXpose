import type { TileJSON, ZoneRing } from './api'

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

// How zone rings are colored. The rings themselves, their keys and distances, come from the
// server (/api/config/); a ring not listed here draws in ZONE_FALLBACK_COLOR.
export const ZONE_COLORS: Partial<Record<string, string>> = {
  hiz_0_5: '#c1121f',
  hiz_5_30: '#f4a100',
  hiz_30_100: '#2a9d8f',
}
export const ZONE_FALLBACK_COLOR = '#6b7280'

export function zoneColor(ring: ZoneRing): string {
  return ZONE_COLORS[ring.key] ?? ZONE_FALLBACK_COLOR
}

// Rings come nearest the structure first, which is how home ignition zones are numbered.
export function zoneLabel(index: number): string {
  return `Zone ${index + 1}`
}

export function zoneRange(ring: ZoneRing): string {
  return `${ring.inner_ft}–${ring.outer_ft} ft`
}
