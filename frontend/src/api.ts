// Shapes of the Django JSON endpoints (src/wuixpose/core/api.py).

export type Bbox = [minLon: number, minLat: number, maxLon: number, maxLat: number]

export interface Summary {
  tract_count: number
  structure_count: number
  bbox: Bbox | null
}

export interface TractDetail {
  id: number
  county_apns: string[]
  area_acres: number
  structure_ids: number[]
}

export interface StructureDetail {
  id: number
  source: string | null
  source_id: string | null
  tract: number | null
  footprint_sq_ft: number
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) {
    throw new Error(`${path}: ${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

export const fetchSummary = (signal?: AbortSignal) => getJson<Summary>('/api/summary/', signal)

export const fetchTract = (id: number, signal?: AbortSignal) =>
  getJson<TractDetail>(`/api/tracts/${id}/`, signal)

export const fetchStructure = (id: number, signal?: AbortSignal) =>
  getJson<StructureDetail>(`/api/structures/${id}/`, signal)

// TileJSON 3.0.0, the subset this app reads. The server builds it in src/wuixpose/core/tiles.py.
export interface TileJSON {
  tilejson: string
  name: string
  tiles: string[]
  minzoom: number
  maxzoom: number
  attribution?: string
  vector_layers: { id: string; fields: Record<string, string>; minzoom?: number; maxzoom?: number }[]
}

export const fetchTileJson = (layer: string, signal?: AbortSignal) =>
  getJson<TileJSON>(`/tiles/${layer}.json`, signal)
