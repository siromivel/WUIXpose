import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchServerConfig, fetchStructure, fetchSummary, fetchTileJson, searchAddresses } from './api'
import { InvalidData } from './validate'

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

function respondWith(body: unknown, init?: ResponseInit) {
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(body), init))
}

const address = {
  id: 7,
  line1: '1172 Valley Ln',
  line2: 'Unincorporated Boulder County, CO 80302',
  lon: -105.4,
  lat: 40.05,
}

describe('fetchServerConfig', () => {
  const rings = [
    { key: 'hiz_0_5', inner_ft: 0, outer_ft: 5 },
    { key: 'hiz_5_30', inner_ft: 5, outer_ft: 30 },
  ]

  it('returns the checked config, without unknown fields', async () => {
    respondWith({
      search: { min_query_length: 3, max_results: 10 },
      zones: { rings, rule_version: 1 },
    })

    expect(await fetchServerConfig()).toEqual({ search: { min_query_length: 3 }, zones: { rings } })
    expect(fetchMock).toHaveBeenCalledWith('/api/config/', { signal: undefined })
  })

  it('names the bad field inside a ring', async () => {
    respondWith({
      search: { min_query_length: 3 },
      zones: { rings: [rings[0], { key: 'hiz_5_30', inner_ft: 5 }] },
    })

    await expect(fetchServerConfig()).rejects.toThrow(
      'Unexpected response from /api/config/: zones.rings[1].outer_ft: expected a number, got undefined',
    )
  })
})

describe('fetchSummary', () => {
  it('returns the checked summary, without unknown fields', async () => {
    respondWith({
      tract_count: 3,
      structure_count: 4,
      address_count: 5,
      bbox: [1, 2, 3, 4],
      extra: true,
    })

    expect(await fetchSummary()).toEqual({
      tract_count: 3,
      structure_count: 4,
      address_count: 5,
      bbox: [1, 2, 3, 4],
    })
  })

  it('accepts a null bbox for an empty database', async () => {
    respondWith({ tract_count: 0, structure_count: 0, address_count: 0, bbox: null })

    expect((await fetchSummary()).bbox).toBeNull()
  })

  it('rejects a bbox without exactly 4 numbers', async () => {
    respondWith({ tract_count: 0, structure_count: 0, address_count: 0, bbox: [1, 2, 3] })

    await expect(fetchSummary()).rejects.toThrow(
      new InvalidData('Unexpected response from /api/summary/: bbox: expected 4 numbers, got an array'),
    )
  })

  it('passes the abort signal to fetch', async () => {
    respondWith({ tract_count: 0, structure_count: 0, address_count: 0, bbox: null })
    const controller = new AbortController()

    await fetchSummary(controller.signal)

    expect(fetchMock).toHaveBeenCalledWith('/api/summary/', { signal: controller.signal })
  })

  it('reports an HTTP error with its status', async () => {
    respondWith({ detail: 'oops' }, { status: 500, statusText: 'Internal Server Error' })

    await expect(fetchSummary()).rejects.toThrow('/api/summary/: 500 Internal Server Error')
  })

  it('lets errors other than a shape mismatch through unchanged', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>not json</html>'))

    await expect(fetchSummary()).rejects.toThrow(SyntaxError)
  })
})

describe('fetchStructure', () => {
  it('names the bad field inside a nested address', async () => {
    respondWith({
      id: 1,
      source: null,
      source_id: null,
      tract: 2,
      tract_county_apns: ['146316400001'],
      tract_addresses: [{ ...address, lat: '40.05' }],
      footprint_sq_ft: 1800,
    })

    await expect(fetchStructure(1)).rejects.toThrow(
      'Unexpected response from /api/structures/1/: tract_addresses[0].lat: expected a number, got string',
    )
  })
})

describe('searchAddresses', () => {
  it('encodes the query and unwraps the results', async () => {
    respondWith({ results: [{ ...address, tract: null }] })

    expect(await searchAddresses('1172 valley & co')).toEqual([{ ...address, tract: null }])
    expect(fetchMock).toHaveBeenCalledWith('/api/search/?q=1172+valley+%26+co', {
      signal: undefined,
    })
  })

  it('requires the tract key on each result', async () => {
    respondWith({ results: [address] })

    await expect(searchAddresses('valley')).rejects.toThrow('results[0].tract: expected a number, got undefined')
  })
})

describe('fetchTileJson', () => {
  it('accepts a layer without optional fields', async () => {
    const tileJson = {
      tilejson: '3.0.0',
      name: 'tracts',
      tiles: ['http://localhost:5173/tiles/tracts/{z}/{x}/{y}.pbf'],
      minzoom: 10,
      maxzoom: 16,
      vector_layers: [{ id: 'tracts', fields: { id: 'Number' } }],
    }
    respondWith(tileJson)

    expect(await fetchTileJson('tracts')).toEqual(tileJson)
    expect(fetchMock).toHaveBeenCalledWith('/tiles/tracts.json', { signal: undefined })
  })
})
