// The Django JSON endpoints (src/wuixpose/core/api.py) and the shapes they return. Every response
// is checked against its shape before the app sees it; the types come from the checks.

import {
  type Check,
  type Checked,
  InvalidData,
  array,
  fail,
  nullable,
  number,
  object,
  optional,
  record,
  string,
} from './validate'

export type Bbox = [minLon: number, minLat: number, maxLon: number, maxLat: number]

const bbox: Check<Bbox> = (value, path) => {
  const values = array(number)(value, path)
  return values.length === 4 ? [values[0], values[1], values[2], values[3]] : fail(path, '4 numbers', value)
}

// A ring drawn around each structure, as distances from its footprint (RINGS in core/zones.py).
const zoneRing = object({ key: string, inner_ft: number, outer_ft: number })
export type ZoneRing = Checked<typeof zoneRing>

// Rules the server sets and the UI follows, so the UI never keeps its own copy of them.
const serverConfig = object({
  search: object({ min_query_length: number }),
  zones: object({ rings: array(zoneRing) }), // nearest the structure first
})
export type ServerConfig = Checked<typeof serverConfig>

const summary = object({
  tract_count: number,
  structure_count: number,
  address_count: number,
  bbox: nullable(bbox),
})
export type Summary = Checked<typeof summary>

const addressShape = {
  id: number,
  line1: string, // number, street and unit: "1172 Valley Ln"
  line2: string, // jurisdiction, state and ZIP: "Unincorporated Boulder County, CO 80302"
  lon: number,
  lat: number,
}
const address = object(addressShape)
export type Address = Checked<typeof address>

const tractDetail = object({
  id: number,
  addresses: array(address),
  county_apns: array(string),
  area_acres: number,
  structure_ids: array(number),
})
export type TractDetail = Checked<typeof tractDetail>

const structureDetail = object({
  id: number,
  source: nullable(string),
  source_id: nullable(string),
  tract: nullable(number),
  tract_county_apns: array(string),
  tract_addresses: array(address),
  footprint_sq_ft: number,
})
export type StructureDetail = Checked<typeof structureDetail>

const searchResult = object({
  ...addressShape,
  tract: nullable(number),
})
export type SearchResult = Checked<typeof searchResult>

// TileJSON 3.0.0, the subset this app reads. The server builds it in src/wuixpose/core/tiles.py.
const tileJson = object({
  tilejson: string,
  name: string,
  tiles: array(string),
  minzoom: number,
  maxzoom: number,
  attribution: optional(string),
  vector_layers: array(
    object({ id: string, fields: record(string), minzoom: optional(number), maxzoom: optional(number) }),
  ),
})
export type TileJSON = Checked<typeof tileJson>

async function getJson<T>(path: string, check: Check<T>, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) {
    throw new Error(`${path}: ${response.status} ${response.statusText}`)
  }
  const body: unknown = await response.json()
  try {
    return check(body, '')
  } catch (err) {
    if (err instanceof InvalidData) throw new InvalidData(`Unexpected response from ${path}: ${err.message}`)
    throw err
  }
}

export const fetchServerConfig = (signal?: AbortSignal) => getJson('/api/config/', serverConfig, signal)

export const fetchSummary = (signal?: AbortSignal) => getJson('/api/summary/', summary, signal)

export const fetchTract = (id: number, signal?: AbortSignal) => getJson(`/api/tracts/${id}/`, tractDetail, signal)

export const fetchStructure = (id: number, signal?: AbortSignal) =>
  getJson(`/api/structures/${id}/`, structureDetail, signal)

export async function searchAddresses(query: string, signal?: AbortSignal): Promise<SearchResult[]> {
  const params = new URLSearchParams({ q: query })
  return (await getJson(`/api/search/?${params}`, object({ results: array(searchResult) }), signal)).results
}

export const fetchTileJson = (layer: string, signal?: AbortSignal) => getJson(`/tiles/${layer}.json`, tileJson, signal)
