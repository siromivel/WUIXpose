import { useEffect, useState } from 'react'

import { type Address, type StructureDetail, type Summary, type TractDetail, fetchStructure, fetchTract } from './api'
import { type LayerVisibility, type Selection, type TileSources, ZONE_RINGS } from './layers'

interface Props {
  summary: Summary | null
  tileSources: TileSources | null
  loadError: string | null
  zoom: number
  visible: LayerVisibility
  onToggle: (layer: keyof LayerVisibility) => void
  selection: Selection
  onSelect: (selection: Selection) => void
}

const LAYER_LABELS: Record<keyof LayerVisibility, string> = {
  tracts: 'Lot lines',
  structures: 'Structures',
  zones: 'Mitigation zones',
  imagery: 'Aerial imagery',
}

const number = new Intl.NumberFormat('en-US')

export function Panel({ summary, tileSources, loadError, zoom, visible, onToggle, selection, onSelect }: Props) {
  return (
    <aside className="panel">
      <header>
        <h1>WUIXpose</h1>
        <p className="subtitle">Wildfire mitigation assessment for homes in the wildland-urban interface</p>
      </header>

      <section>
        <h2>Loaded</h2>
        {loadError ? (
          <p className="error">Couldn't reach the API: {loadError}</p>
        ) : !summary ? (
          <p className="muted">Loading…</p>
        ) : summary.tract_count === 0 ? (
          <p className="muted">
            No data yet. Run <code>manage.py ingest_boulder</code>, then reload.
          </p>
        ) : (
          <dl className="stats">
            <div>
              <dt>Lots</dt>
              <dd>{number.format(summary.tract_count)}</dd>
            </div>
            <div>
              <dt>Structures</dt>
              <dd>{number.format(summary.structure_count)}</dd>
            </div>
            <div>
              <dt>Addresses</dt>
              <dd>{number.format(summary.address_count)}</dd>
            </div>
          </dl>
        )}
      </section>

      <section>
        <h2>Layers</h2>
        {(Object.keys(LAYER_LABELS) as (keyof LayerVisibility)[]).map((layer) => {
          const minZoom = layer === 'imagery' ? 0 : (tileSources?.[layer].minzoom ?? 0)
          return (
            <label key={layer} className="toggle">
              <input type="checkbox" checked={visible[layer]} onChange={() => onToggle(layer)} />
              <span>{LAYER_LABELS[layer]}</span>
              {visible[layer] && zoom < minZoom && <span className="hint">zoom in to see</span>}
            </label>
          )
        })}
        {visible.zones && (
          <ul className="legend">
            {ZONE_RINGS.map((ring) => (
              <li key={ring.key}>
                <span className="swatch" style={{ background: ring.color }} />
                {ring.label}
                <span className="range">{ring.range} from the structure</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="selection">
        <h2>Selected</h2>
        {!selection ? (
          <p className="muted">Click a lot or a building on the map.</p>
        ) : selection.kind === 'tract' ? (
          <TractCard id={selection.id} />
        ) : (
          <StructureCard id={selection.id} onSelectTract={(id) => onSelect({ kind: 'tract', id })} />
        )}
      </section>
    </aside>
  )
}

function useDetail<T>(id: number, load: (id: number, signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<{ id: number; data?: T; error?: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    load(id, controller.signal)
      .then((data) => setState({ id, data }))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setState({ id, error: String(err) })
      })
    return () => controller.abort()
  }, [id, load])
  // Ignore a result still showing for the previous selection.
  return state?.id === id ? state : null
}

// Lots like apartment complexes carry hundreds of addresses; show the first few.
const ADDRESSES_SHOWN = 3

function AddressList({ addresses }: { addresses: Address[] }) {
  if (addresses.length === 0) return <p className="muted address">No address on record</p>
  const shown = addresses.slice(0, ADDRESSES_SHOWN)
  // Units on one lot usually share a city and ZIP; repeat it only when they differ.
  const sameLine2 = shown.every((a) => a.line2 === shown[0].line2)
  return (
    <ul className="addresses">
      {shown.map((a, i) => (
        <li key={a.id}>
          {a.line1}
          {(!sameLine2 || i === shown.length - 1) && <span className="line2">{a.line2}</span>}
        </li>
      ))}
      {addresses.length > shown.length && (
        <li className="muted">and {number.format(addresses.length - shown.length)} more</li>
      )}
    </ul>
  )
}

function TractCard({ id }: { id: number }) {
  const state = useDetail<TractDetail>(id, fetchTract)
  if (!state) return <p className="muted">Loading…</p>
  if (state.error || !state.data) return <p className="error">{state.error}</p>
  const tract = state.data
  return (
    <div className="card">
      <h3>Lot</h3>
      <AddressList addresses={tract.addresses} />
      <dl>
        <dt>County parcel no.</dt>
        <dd>{tract.county_apns.join(', ') || '—'}</dd>
        <dt>Area</dt>
        <dd>{tract.area_acres.toFixed(2)} acres</dd>
        <dt>Structures</dt>
        <dd>{tract.structure_ids.length}</dd>
      </dl>
      <p className="id">Tract {tract.id}</p>
    </div>
  )
}

function StructureCard({ id, onSelectTract }: { id: number; onSelectTract: (id: number) => void }) {
  const state = useDetail<StructureDetail>(id, fetchStructure)
  if (!state) return <p className="muted">Loading…</p>
  if (state.error || !state.data) return <p className="error">{state.error}</p>
  const structure = state.data
  return (
    <div className="card">
      <h3>Structure</h3>
      {structure.tract !== null && <AddressList addresses={structure.tract_addresses} />}
      <dl>
        <dt>Footprint</dt>
        <dd>{number.format(structure.footprint_sq_ft)} sq ft</dd>
        <dt>County structure ID</dt>
        <dd>{structure.source_id ?? '—'}</dd>
        <dt>Lot</dt>
        <dd>
          {structure.tract === null ? (
            <span className="muted">none (straddles a lot line or outside parcel data)</span>
          ) : (
            <button
              type="button"
              className="link"
              title="Select this lot"
              onClick={() => onSelectTract(structure.tract!)}
            >
              {structure.tract_county_apns.join(', ') || 'Select its lot'}
            </button>
          )}
        </dd>
      </dl>
      <p className="id">Structure {structure.id}</p>
    </div>
  )
}
