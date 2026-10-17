import { useEffect, useState } from 'react'

import {
  type SearchResult,
  type ServerConfig,
  type Summary,
  fetchServerConfig,
  fetchSummary,
  fetchTileJson,
} from './api'
import { type LayerVisibility, type Selection, TILE_LAYERS, type TileSources } from './layers'
import { type Focus, MapView } from './MapView'
import { Panel } from './Panel'

// What the app needs before it can start: the rules the server sets, where the data is, and how
// its tiles are served.
interface AppData {
  serverConfig: ServerConfig
  summary: Summary
  tileSources: TileSources
}

async function loadAppData(signal: AbortSignal): Promise<AppData> {
  const [serverConfig, summary, ...tileJsons] = await Promise.all([
    fetchServerConfig(signal),
    fetchSummary(signal),
    ...TILE_LAYERS.map((layer) => fetchTileJson(layer, signal)),
  ])
  const tileSources = Object.fromEntries(TILE_LAYERS.map((layer, i) => [layer, tileJsons[i]])) as TileSources
  return { serverConfig, summary, tileSources }
}

export default function App() {
  const [appData, setAppData] = useState<AppData | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [visible, setVisible] = useState<LayerVisibility>({
    tracts: true,
    structures: true,
    zones: true,
    imagery: false,
  })
  const [selection, setSelection] = useState<Selection>(null)
  const [zoom, setZoom] = useState(0)
  const [focus, setFocus] = useState<Focus | null>(null)

  // Go to a searched address and select its lot. One without a lot clears the selection rather
  // than leave a lot elsewhere selected.
  function pickAddress(result: SearchResult) {
    setFocus({ lon: result.lon, lat: result.lat })
    setSelection(result.tract === null ? null : { kind: 'tract', id: result.tract })
  }

  useEffect(() => {
    const controller = new AbortController()
    loadAppData(controller.signal)
      .then(setAppData)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setLoadError(String(err))
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="app">
      <Panel
        serverConfig={appData?.serverConfig ?? null}
        summary={appData?.summary ?? null}
        tileSources={appData?.tileSources ?? null}
        loadError={loadError}
        zoom={zoom}
        visible={visible}
        onToggle={(layer) => setVisible((v) => ({ ...v, [layer]: !v[layer] }))}
        selection={selection}
        onSelect={setSelection}
        onPickAddress={pickAddress}
      />
      {appData && (
        <MapView
          initialBbox={appData.summary.bbox}
          tileSources={appData.tileSources}
          zoneRings={appData.serverConfig.zones.rings}
          visible={visible}
          focus={focus}
          selection={selection}
          onSelect={setSelection}
          onZoom={setZoom}
        />
      )}
    </div>
  )
}
