// Runtime checks for data from outside the app, such as API responses. Each check also gives the
// TypeScript type of what it accepts (Checked<typeof check>), so a type and its check can't drift.

// Returns the value as T, or throws InvalidData. `path` locates the value in error messages.
export type Check<T> = (value: unknown, path: string) => T
export type Checked<C> = C extends Check<infer T> ? T : never

export class InvalidData extends Error {
  name = 'InvalidData'
}

export function fail(path: string, expected: string, value: unknown): never {
  const got = value === null ? 'null' : Array.isArray(value) ? 'an array' : typeof value
  throw new InvalidData(`${path || 'value'}: expected ${expected}, got ${got}`)
}

const at = (path: string, key: string | number) =>
  typeof key === 'number' ? `${path}[${key}]` : path ? `${path}.${key}` : key

export const number: Check<number> = (value, path) =>
  typeof value === 'number' && Number.isFinite(value) ? value : fail(path, 'a number', value)

export const string: Check<string> = (value, path) =>
  typeof value === 'string' ? value : fail(path, 'a string', value)

export const nullable =
  <T>(check: Check<T>): Check<T | null> =>
  (value, path) =>
    value === null ? null : check(value, path)

export const optional =
  <T>(check: Check<T>): Check<T | undefined> =>
  (value, path) =>
    value === undefined ? undefined : check(value, path)

export const array =
  <T>(check: Check<T>): Check<T[]> =>
  (value, path) =>
    Array.isArray(value) ? value.map((item, i) => check(item, at(path, i))) : fail(path, 'an array', value)

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// An object with any keys, each value passing `check`.
export const record =
  <T>(check: Check<T>): Check<Record<string, T>> =>
  (value, path) =>
    isObject(value)
      ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, check(item, at(path, key))]))
      : fail(path, 'an object', value)

// An object with the keys in `shape`. Keys not in the shape are dropped, so code only sees what
// was checked.
export function object<S extends Record<string, Check<unknown>>>(shape: S): Check<{ [K in keyof S]: Checked<S[K]> }> {
  return (value, path) => {
    if (!isObject(value)) return fail(path, 'an object', value)
    const checked: Record<string, unknown> = {}
    for (const [key, check] of Object.entries(shape)) checked[key] = check(value[key], at(path, key))
    // Every key in the shape was checked just above, which TypeScript can't follow through the loop.
    return checked as { [K in keyof S]: Checked<S[K]> }
  }
}
