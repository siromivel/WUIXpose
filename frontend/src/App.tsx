import { useEffect, useState } from 'react'

import { type Summary, fetchSummary } from './api'
import { type LayerVisibility, type Selection } from './layers'
import { MapView } from './MapView'
import { Panel } from './Panel'

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [visible, setVisible] = useState<LayerVisibility>({ tracts: true, structures: true, imagery: false })
  const [selection, setSelection] = useState<Selection>(null)
  const [zoom, setZoom] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchSummary(controller.signal)
      .then(setSummary)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setSummaryError(String(err))
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="app">
      <Panel
        summary={summary}
        summaryError={summaryError}
        zoom={zoom}
        visible={visible}
        onToggle={(layer) => setVisible((v) => ({ ...v, [layer]: !v[layer] }))}
        selection={selection}
        onSelect={setSelection}
      />
      {/* Wait for the summary so the map can open on the loaded data. */}
      {(summary || summaryError) && (
        <MapView
          initialBbox={summary?.bbox ?? null}
          visible={visible}
          selection={selection}
          onSelect={setSelection}
          onZoom={setZoom}
        />
      )}
    </div>
  )
}
