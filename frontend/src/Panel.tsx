import { useEffect, useState } from 'react'

import { type StructureDetail, type Summary, type TractDetail, fetchStructure, fetchTract } from './api'
import { type LayerVisibility, type Selection, type TileSources } from './layers'

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
  imagery: 'Aerial imagery',
}

const number = new Intl.NumberFormat('en-US')

export function Panel({ summary, tileSources, loadError, zoom, visible, onToggle, selection, onSelect }: Props) {
  return (
    <aside className="panel">
      <header>
        <h1>WUIXpose</h1>
        <p className="subtitle">Wildfire mitigation for homes in the wildland-urban interface</p>
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

function TractCard({ id }: { id: number }) {
  const state = useDetail<TractDetail>(id, fetchTract)
  if (!state) return <p className="muted">Loading…</p>
  if (state.error || !state.data) return <p className="error">{state.error}</p>
  const tract = state.data
  return (
    <div className="card">
      <h3>Lot</h3>
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
            <button type="button" className="link" onClick={() => onSelectTract(structure.tract!)}>
              Select its lot
            </button>
          )}
        </dd>
      </dl>
      <p className="id">Structure {structure.id}</p>
    </div>
  )
}
