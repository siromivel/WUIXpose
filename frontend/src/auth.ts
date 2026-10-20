// Signing in, through django-allauth's headless API for browsers (README, "Accounts"). It runs on
// Django's session cookie, so the app never holds a token; every response is checked like api.ts's.

import { type Checked, InvalidData, array, boolean, nullable, object, optional, string } from './validate'

const BASE = '/api/auth/browser/v1'

const user = object({
  display: string,
  email: optional(nullable(string)),
})
export type User = Checked<typeof user>

// Where a visitor stands. Signing up, or signing in before verifying, leaves the session waiting
// for the code emailed to them.
export type AuthState = { status: 'signedIn'; user: User } | { status: 'signedOut' } | { status: 'verifyEmail' }

const signedIn = object({ data: object({ user }) })
const signedOut = object({
  data: object({ flows: array(object({ id: string, is_pending: optional(boolean) })) }),
})
const failed = object({ errors: array(object({ message: string })) })

// The ways to sign in that the server offers besides a password, e.g. a Keycloak realm.
const provider = object({ id: string, name: string })
export type Provider = Checked<typeof provider>
const authConfig = object({ data: object({ socialaccount: object({ providers: array(provider) }) }) })

// A request the server turned down for a reason the person can fix, e.g. a wrong password.
export class AuthError extends Error {
  name = 'AuthError'
}

// Django's CSRF token, which allauth sets as a cookie on its first response. Every request other
// than a GET must echo it in a header.
export function csrfToken(cookies: string = document.cookie): string {
  const match = cookies.match(/(?:^|;\s*)csrftoken=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : ''
}

function checked<T>(path: string, check: (value: unknown, path: string) => T, body: unknown): T {
  try {
    return check(body, '')
  } catch (err) {
    if (err instanceof InvalidData) throw new InvalidData(`Unexpected response from ${path}: ${err.message}`)
    throw err
  }
}

async function request(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<AuthState> {
  const url = `${BASE}${path}`
  const response = await fetch(url, {
    method,
    signal,
    headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  // Only these carry allauth's JSON; anything else (a 500, a proxy error) may not be JSON at all.
  if (![200, 400, 401].includes(response.status)) {
    throw new Error(`${url}: ${response.status} ${response.statusText}`)
  }
  const json: unknown = await response.json()
  if (response.status === 200) return { status: 'signedIn', user: checked(url, signedIn, json).data.user }
  if (response.status === 401) {
    const pending = checked(url, signedOut, json).data.flows.find((flow) => flow.is_pending)
    return pending?.id === 'verify_email' ? { status: 'verifyEmail' } : { status: 'signedOut' }
  }
  const messages = checked(url, failed, json).errors.map((e) => e.message)
  throw new AuthError(messages.join(' '))
}

export const fetchSession = (signal?: AbortSignal) => request('GET', '/auth/session', undefined, signal)

export const signIn = (email: string, password: string) => request('POST', '/auth/login', { email, password })

export const signUp = (email: string, password: string) => request('POST', '/auth/signup', { email, password })

export const verifyEmail = (code: string) => request('POST', '/auth/email/verify', { key: code })

export const signOut = () => request('DELETE', '/auth/session')

export async function fetchProviders(signal?: AbortSignal): Promise<Provider[]> {
  const url = `${BASE}/config`
  const response = await fetch(url, { signal })
  if (!response.ok) throw new Error(`${url}: ${response.status} ${response.statusText}`)
  return checked(url, authConfig, await response.json()).data.socialaccount.providers
}

// Signing in with a provider leaves the app: the browser posts a form to Django, which sends it on
// to the provider and, once signed in there, back to `returnTo` with the session set. Django keeps
// the provider's tokens; the app only ever sees the session.
export function redirectToProvider(providerId: string, returnTo: string = window.location.pathname) {
  const form = document.createElement('form')
  form.method = 'POST'
  form.action = `${BASE}/auth/provider/redirect`
  const fields = { provider: providerId, process: 'login', callback_url: returnTo, csrfmiddlewaretoken: csrfToken() }
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.name = name
    input.value = value
    form.append(input)
  }
  document.body.append(form)
  form.submit()
}
