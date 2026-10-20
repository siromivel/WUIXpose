import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthError, csrfToken, fetchProviders, fetchSession, signIn, signOut, signUp, verifyEmail } from './auth'

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('document', { cookie: 'sessionid=abc; csrftoken=t0ken' })
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

function respondWith(status: number, body: unknown) {
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(body), { status }))
}

const user = { id: 1, display: 'pat', email: 'pat@example.com', has_usable_password: true }
const authenticated = { status: 200, data: { user, methods: [] }, meta: { is_authenticated: true } }
const unauthenticated = (flows: unknown[]) => ({ status: 401, data: { flows }, meta: { is_authenticated: false } })

describe('csrfToken', () => {
  it('reads the csrftoken cookie', () => {
    expect(csrfToken('a=1; csrftoken=abc%3D; b=2')).toBe('abc=')
    expect(csrfToken('csrftoken=first')).toBe('first')
  })

  it('is empty before Django has set one', () => {
    expect(csrfToken('sessionid=x')).toBe('')
  })
})

describe('fetchSession', () => {
  it('returns the signed-in user, without unknown fields', async () => {
    respondWith(200, authenticated)

    expect(await fetchSession()).toEqual({
      status: 'signedIn',
      user: { display: 'pat', email: 'pat@example.com' },
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/browser/v1/auth/session', {
      method: 'GET',
      signal: undefined,
      headers: {},
      body: undefined,
    })
  })

  it('is signed out when nothing is pending', async () => {
    respondWith(401, unauthenticated([{ id: 'login' }, { id: 'signup' }]))

    expect(await fetchSession()).toEqual({ status: 'signedOut' })
  })

  it('waits for the emailed code when verification is pending', async () => {
    respondWith(401, unauthenticated([{ id: 'login' }, { id: 'verify_email', is_pending: true }]))

    expect(await fetchSession()).toEqual({ status: 'verifyEmail' })
  })

  it('reports a server error without reading its body', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>oops</html>', { status: 502, statusText: 'Bad Gateway' }))

    await expect(fetchSession()).rejects.toThrow('/api/auth/browser/v1/auth/session: 502 Bad Gateway')
  })

  it('names the bad field', async () => {
    respondWith(200, { ...authenticated, data: { user: { ...user, display: 1 } } })

    await expect(fetchSession()).rejects.toThrow(
      'Unexpected response from /api/auth/browser/v1/auth/session: data.user.display: expected a string, got number',
    )
  })
})

describe('signIn', () => {
  it('posts the credentials as JSON with the CSRF token', async () => {
    respondWith(200, authenticated)

    await signIn('pat@example.com', 'correct horse battery')

    expect(fetchMock).toHaveBeenCalledWith('/api/auth/browser/v1/auth/login', {
      method: 'POST',
      signal: undefined,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': 't0ken' },
      body: JSON.stringify({ email: 'pat@example.com', password: 'correct horse battery' }),
    })
  })

  // Django rotates the token when someone signs in, so a token read earlier would be refused.
  it('reads the CSRF token afresh for every request', async () => {
    respondWith(200, authenticated)
    await signIn('pat@example.com', 'correct horse battery')
    vi.stubGlobal('document', { cookie: 'csrftoken=rotated' })
    respondWith(401, unauthenticated([{ id: 'login' }]))

    await signOut()

    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/auth/browser/v1/auth/session',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json', 'X-CSRFToken': 'rotated' } }),
    )
  })

  it("throws the server's messages for a rejected sign-in", async () => {
    respondWith(400, {
      status: 400,
      errors: [{ message: 'The email address and/or password you specified are not correct.', code: 'x' }],
    })

    await expect(signIn('pat@example.com', 'wrong')).rejects.toThrow(
      new AuthError('The email address and/or password you specified are not correct.'),
    )
  })
})

describe('signUp and verifyEmail', () => {
  it('waits for the code after signing up, then signs in with it', async () => {
    respondWith(401, unauthenticated([{ id: 'verify_email', is_pending: true }]))
    expect(await signUp('pat@example.com', 'correct horse battery')).toEqual({ status: 'verifyEmail' })

    respondWith(200, authenticated)
    expect(await verifyEmail('TLKK-MMTR')).toMatchObject({ status: 'signedIn' })
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/auth/browser/v1/auth/email/verify',
      expect.objectContaining({ body: JSON.stringify({ key: 'TLKK-MMTR' }) }),
    )
  })
})

describe('signOut', () => {
  it('deletes the session, which answers signed out', async () => {
    respondWith(401, unauthenticated([{ id: 'login' }]))

    expect(await signOut()).toEqual({ status: 'signedOut' })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/browser/v1/auth/session',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })
})

describe('fetchProviders', () => {
  it('returns the providers the server offers', async () => {
    respondWith(200, {
      status: 200,
      data: {
        account: { login_methods: ['email'] },
        socialaccount: { providers: [{ id: 'keycloak', name: 'Keycloak', flows: ['provider_redirect'] }] },
      },
    })

    expect(await fetchProviders()).toEqual([{ id: 'keycloak', name: 'Keycloak' }])
  })
})
