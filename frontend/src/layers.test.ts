import { describe, expect, it } from 'vitest'

import { ZONE_COLORS, ZONE_FALLBACK_COLOR, zoneColor, zoneLabel, zoneRange } from './layers'

describe('zone presentation', () => {
  it('numbers zones from the structure out', () => {
    expect([0, 1, 2].map(zoneLabel)).toEqual(['Zone 1', 'Zone 2', 'Zone 3'])
  })

  it('writes a ring as its distances from the structure', () => {
    expect(zoneRange({ key: 'hiz_0_5', inner_ft: 0, outer_ft: 5 })).toBe('0–5 ft')
    expect(zoneRange({ key: 'hiz_30_100', inner_ft: 30, outer_ft: 100 })).toBe('30–100 ft')
  })

  it('colors a ring by its key, and one it has no color for in the fallback', () => {
    expect(zoneColor({ key: 'hiz_0_5', inner_ft: 0, outer_ft: 5 })).toBe(ZONE_COLORS.hiz_0_5)
    expect(zoneColor({ key: 'hiz_100_200', inner_ft: 100, outer_ft: 200 })).toBe(ZONE_FALLBACK_COLOR)
  })
})
