import { type FormEvent, useEffect, useState } from 'react'

import {
  AuthError,
  type AuthState,
  type Provider,
  fetchProviders,
  fetchSession,
  redirectToProvider,
  signIn,
  signOut,
  signUp,
  verifyEmail,
} from './auth'

// A provider sign-in that failed comes back to the app with an `error` query parameter.
function takeProviderError(): string | null {
  const params = new URLSearchParams(window.location.search)
  const error = params.get('error')
  if (error === null) return null
  params.delete('error')
  const query = params.toString()
  window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`)
  return `Signing in with the provider didn't work (${error}).`
}

export function Account() {
  const [state, setState] = useState<AuthState | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [error, setError] = useState<string | null>(takeProviderError)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([fetchSession(controller.signal), fetchProviders(controller.signal)])
      .then(([session, offered]) => {
        setState(session)
        setProviders(offered)
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(String(err))
      })
    return () => controller.abort()
  }, [])

  async function act(action: () => Promise<AuthState>) {
    setBusy(true)
    setError(null)
    try {
      setState(await action())
    } catch (err: unknown) {
      setError(err instanceof AuthError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="account">
      {!state ? (
        !error && <p className="muted">Loading…</p>
      ) : state.status === 'signedIn' ? (
        <p className="signed-in">
          Signed in as {state.user.email ?? state.user.display}
          <button type="button" className="link" disabled={busy} onClick={() => act(signOut)}>
            Sign out
          </button>
        </p>
      ) : state.status === 'verifyEmail' ? (
        <VerifyForm busy={busy} onVerify={(code) => act(() => verifyEmail(code))} onCancel={() => act(signOut)} />
      ) : (
        <SignInForm
          busy={busy}
          providers={providers}
          onSignIn={(email, password) => act(() => signIn(email, password))}
          onSignUp={(email, password) => act(() => signUp(email, password))}
        />
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

interface SignInProps {
  busy: boolean
  providers: Provider[]
  onSignIn: (email: string, password: string) => void
  onSignUp: (email: string, password: string) => void
}

function SignInForm({ busy, providers, onSignIn, onSignUp }: SignInProps) {
  const [creating, setCreating] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    ;(creating ? onSignUp : onSignIn)(email, password)
  }

  return (
    <form onSubmit={submit}>
      <input
        type="email"
        placeholder="Email"
        aria-label="Email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <input
        type="password"
        placeholder={creating ? 'Password (15 characters or more)' : 'Password'}
        aria-label="Password"
        autoComplete={creating ? 'new-password' : 'current-password'}
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <button type="submit" className="primary" disabled={busy}>
        {creating ? 'Create account' : 'Sign in'}
      </button>
      <p className="muted switch">
        {creating ? 'Have an account? ' : 'New here? '}
        <button type="button" className="link" onClick={() => setCreating(!creating)}>
          {creating ? 'Sign in' : 'Create an account'}
        </button>
      </p>
      {providers.map((provider) => (
        <button key={provider.id} type="button" disabled={busy} onClick={() => redirectToProvider(provider.id)}>
          Sign in with {provider.name}
        </button>
      ))}
    </form>
  )
}

interface VerifyProps {
  busy: boolean
  onVerify: (code: string) => void
  onCancel: () => void
}

function VerifyForm({ busy, onVerify, onCancel }: VerifyProps) {
  const [code, setCode] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    onVerify(code.trim())
  }

  return (
    <form onSubmit={submit}>
      <p className="muted">Enter the code we emailed you to confirm your address.</p>
      <input
        placeholder="Code"
        aria-label="Code"
        autoComplete="one-time-code"
        required
        value={code}
        onChange={(event) => setCode(event.target.value)}
      />
      <button type="submit" className="primary" disabled={busy}>
        Confirm
      </button>
      <p className="muted switch">
        <button type="button" className="link" disabled={busy} onClick={onCancel}>
          Start over
        </button>
      </p>
    </form>
  )
}
