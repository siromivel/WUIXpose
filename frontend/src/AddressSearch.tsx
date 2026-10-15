import { type KeyboardEvent, useEffect, useId, useState } from 'react'

import { type SearchResult, searchAddresses } from './api'

// The server answers shorter queries with nothing (MIN_QUERY_LENGTH in core/search.py).
const MIN_QUERY_LENGTH = 3
// Wait for a pause in typing before asking the server.
const DEBOUNCE_MS = 200

interface Props {
  onPick: (result: SearchResult) => void
}

export function AddressSearch({ onPick }: Props) {
  const [query, setQuery] = useState('')
  // The latest answer, kept on screen while the next query is in flight.
  const [answer, setAnswer] = useState<{ query: string; results?: SearchResult[]; error?: string } | null>(null)
  const [active, setActive] = useState(0)
  const [open, setOpen] = useState(false)
  const listId = useId()

  const trimmed = query.trim()
  const searchable = trimmed.length >= MIN_QUERY_LENGTH

  useEffect(() => {
    if (!searchable) return
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const results = await searchAddresses(trimmed, controller.signal)
        setAnswer({ query: trimmed, results })
        setActive(0)
      } catch (err: unknown) {
        if (!controller.signal.aborted) setAnswer({ query: trimmed, error: String(err) })
      }
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [trimmed, searchable])

  const results = (searchable && answer?.results) || []
  const showList = open && searchable

  function pick(result: SearchResult) {
    setOpen(false)
    onPick(result)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
      if (results.length === 0) return
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (i + step + results.length) % results.length)
    } else if (event.key === 'Enter' && showList && results[active]) {
      pick(results[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="search">
      <input
        type="search"
        placeholder="Find an address"
        aria-label="Find an address"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={showList && results.length > 0}
        aria-controls={listId}
        aria-activedescendant={showList && results[active] ? `${listId}-${active}` : undefined}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {showList &&
        answer &&
        (answer.error ? (
          <p className="error">Search failed: {answer.error}</p>
        ) : results.length === 0 ? (
          <p className="muted">No matching address</p>
        ) : (
          <ul id={listId} role="listbox" className="results">
            {results.map((result, i) => (
              <li
                key={result.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                // mousedown would blur the input and close the list before the click lands.
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(result)}
              >
                {result.line1}
                <span className="line2">{result.line2}</span>
              </li>
            ))}
          </ul>
        ))}
    </div>
  )
}
