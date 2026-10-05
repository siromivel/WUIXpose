import { useEffect, useState } from 'react'

import { type Summary, fetchSummary, fetchTileJson } from './api'
import { type LayerVisibility, type Selection, TILE_LAYERS, type TileSources } from './layers'
import { MapView } from './MapView'
import { Panel } from './Panel'

// What the map needs before it can be built: where the data is, and how its tiles are served.
interface MapData {
  summary: Summary
  tileSources: TileSources
}

async function loadMapData(signal: AbortSignal): Promise<MapData> {
  const [summary, ...tileJsons] = await Promise.all([
    fetchSummary(signal),
    ...TILE_LAYERS.map((layer) => fetchTileJson(layer, signal)),
  ])
  const tileSources = Object.fromEntries(TILE_LAYERS.map((layer, i) => [layer, tileJsons[i]])) as TileSources
  return { summary, tileSources }
}

export default function App() {
  const [mapData, setMapData] = useState<MapData | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [visible, setVisible] = useState<LayerVisibility>({ tracts: true, structures: true, imagery: false })
  const [selection, setSelection] = useState<Selection>(null)
  const [zoom, setZoom] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    loadMapData(controller.signal)
      .then(setMapData)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setLoadError(String(err))
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="app">
      <Panel
        summary={mapData?.summary ?? null}
        tileSources={mapData?.tileSources ?? null}
        loadError={loadError}
        zoom={zoom}
        visible={visible}
        onToggle={(layer) => setVisible((v) => ({ ...v, [layer]: !v[layer] }))}
        selection={selection}
        onSelect={setSelection}
      />
      {mapData && (
        <MapView
          initialBbox={mapData.summary.bbox}
          tileSources={mapData.tileSources}
          visible={visible}
          selection={selection}
          onSelect={setSelection}
          onZoom={setZoom}
        />
      )}
    </div>
  )
}
