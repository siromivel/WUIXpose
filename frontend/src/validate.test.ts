import { describe, expect, expectTypeOf, it } from 'vitest'

import {
  type Checked,
  InvalidData,
  array,
  nullable,
  number,
  object,
  optional,
  record,
  string,
} from './validate'

describe('number', () => {
  it('accepts finite numbers', () => {
    expect(number(0, 'n')).toBe(0)
    expect(number(-1.5, 'n')).toBe(-1.5)
  })

  // JSON can't carry these, but a check that let them through would hide a bug upstream.
  it.each([NaN, Infinity, -Infinity])('rejects %s', (value) => {
    expect(() => number(value, 'n')).toThrow('n: expected a number, got number')
  })

  it('rejects numeric strings', () => {
    expect(() => number('1', 'n')).toThrow('n: expected a number, got string')
  })
})

describe('string', () => {
  it('accepts strings, including empty ones', () => {
    expect(string('', 's')).toBe('')
  })

  it('rejects other types', () => {
    expect(() => string(1, 's')).toThrow('s: expected a string, got number')
  })
})

describe('error messages', () => {
  it('throw InvalidData', () => {
    expect(() => number('x', 'n')).toThrow(InvalidData)
  })

  it('name null and arrays rather than calling them objects', () => {
    expect(() => string(null, 's')).toThrow('got null')
    expect(() => string([], 's')).toThrow('got an array')
  })

  it('call a value at the root "value"', () => {
    expect(() => number('x', '')).toThrow('value: expected a number, got string')
  })
})

describe('nullable', () => {
  const check = nullable(number)

  it('accepts null and the inner type', () => {
    expect(check(null, 'n')).toBeNull()
    expect(check(1, 'n')).toBe(1)
  })

  it('rejects undefined', () => {
    expect(() => check(undefined, 'n')).toThrow('n: expected a number, got undefined')
  })
})

describe('optional', () => {
  const check = optional(number)

  it('accepts undefined and the inner type', () => {
    expect(check(undefined, 'n')).toBeUndefined()
    expect(check(1, 'n')).toBe(1)
  })

  it('rejects null', () => {
    expect(() => check(null, 'n')).toThrow('n: expected a number, got null')
  })
})

describe('array', () => {
  const check = array(number)

  it('checks every item', () => {
    expect(check([1, 2], 'a')).toEqual([1, 2])
    expect(check([], 'a')).toEqual([])
  })

  it('names the bad item by index', () => {
    expect(() => check([1, 'two'], 'a')).toThrow('a[1]: expected a number, got string')
    expect(() => check([1, 'two'], '')).toThrow('[1]: expected a number, got string')
  })

  it('rejects non-arrays', () => {
    expect(() => check({ 0: 1 }, 'a')).toThrow('a: expected an array, got object')
  })
})

describe('record', () => {
  const check = record(string)

  it('checks every value', () => {
    expect(check({ a: 'x', b: 'y' }, 'r')).toEqual({ a: 'x', b: 'y' })
  })

  it('names the bad value by key', () => {
    expect(() => check({ a: 'x', b: 1 }, 'r')).toThrow('r.b: expected a string, got number')
  })

  it('rejects arrays and null', () => {
    expect(() => check([], 'r')).toThrow('r: expected an object, got an array')
    expect(() => check(null, 'r')).toThrow('r: expected an object, got null')
  })
})

describe('object', () => {
  const check = object({
    id: number,
    name: nullable(string),
    tags: array(object({ label: string })),
  })

  it('returns only the keys in the shape', () => {
    expect(
      check({ id: 1, name: null, tags: [{ label: 'a', extra: true }], extra: 'dropped' }, ''),
    ).toEqual({
      id: 1,
      name: null,
      tags: [{ label: 'a' }],
    })
  })

  it('names nested fields by path', () => {
    expect(() => check({ id: 1, name: null, tags: [{ label: 'a' }, { label: 2 }] }, '')).toThrow(
      'tags[1].label: expected a string, got number',
    )
  })

  it('reports a missing key as undefined', () => {
    expect(() => check({ name: null, tags: [] }, '')).toThrow(
      'id: expected a number, got undefined',
    )
  })

  it('rejects arrays and null', () => {
    expect(() => check([], '')).toThrow('value: expected an object, got an array')
    expect(() => check(null, '')).toThrow('value: expected an object, got null')
  })

  it('gives the checked type', () => {
    expectTypeOf<Checked<typeof check>>().toEqualTypeOf<{
      id: number
      name: string | null
      tags: { label: string }[]
    }>()
  })
})
