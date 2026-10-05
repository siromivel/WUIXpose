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

// MapLibre fetches tiles itself and needs absolute URLs.
export const tileUrl = (layer: 'tracts' | 'structures') =>
  `${window.location.origin}/tiles/${layer}/{z}/{x}/{y}.mvt`
