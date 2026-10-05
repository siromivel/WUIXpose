import {
  type ExpressionSpecification,
  type FeatureIdentifier,
  type MapGeoJSONFeature,
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type StyleSpecification,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { useEffect, useRef, useState } from 'react'

import { type Bbox, tileUrl } from './api'
import { type LayerVisibility, MIN_ZOOM, type Selection } from './layers'

// MapLibre looks for its worker next to its own module file, which isn't where Vite puts
// either one. Let Vite bundle the worker and tell MapLibre where it went.
setWorkerUrl(maplibreWorkerUrl)

interface Props {
  initialBbox: Bbox | null
  visible: LayerVisibility
  selection: Selection
  onSelect: (selection: Selection) => void
  onZoom: (zoom: number) => void
}

// Past this the client overzooms the last tiles it fetched instead of requesting more.
const MAX_TILE_ZOOM = 16

// Light, label-friendly vector basemap. Free, no key: https://openfreemap.org
const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
// Used if the basemap can't be fetched, so lots and structures still draw on a plain ground.
const PLAIN_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#eceee8' } }],
}
// USGS National Map orthoimagery, public domain.
const IMAGERY_TILES =
  'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}'

// Unincorporated Boulder County foothills, for when nothing is loaded yet.
const FALLBACK_CENTER: [number, number] = [-105.35, 40.05]

const COLORS = {
  tract: '#3d5a80',
  tractSelected: '#1d3557',
  structure: '#e07a2f',
  structureSelected: '#9d2d0f',
}

const selected: ExpressionSpecification = ['boolean', ['feature-state', 'selected'], false]

function addDataLayers(map: MapLibreMap) {
  map.addSource('imagery', {
    type: 'raster',
    tiles: [IMAGERY_TILES],
    tileSize: 256,
    maxzoom: 16,
    attribution: 'Imagery: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS</a>',
  })
  map.addLayer({
    id: 'imagery',
    type: 'raster',
    source: 'imagery',
    layout: { visibility: 'none' },
  })

  const countyAttribution =
    'Parcels and footprints: <a href="https://opendata-bouldercounty.hub.arcgis.com/">Boulder County</a>, CC BY 4.0'
  for (const layer of ['tracts', 'structures'] as const) {
    map.addSource(layer, {
      type: 'vector',
      tiles: [tileUrl(layer)],
      minzoom: MIN_ZOOM[layer],
      maxzoom: MAX_TILE_ZOOM,
      attribution: countyAttribution,
    })
  }

  map.addLayer({
    id: 'tracts-fill',
    type: 'fill',
    source: 'tracts',
    'source-layer': 'tracts',
    paint: {
      // Near-transparent rather than invisible so the whole lot answers clicks.
      'fill-color': COLORS.tract,
      'fill-opacity': ['case', selected, 0.22, 0.03],
    },
  })
  map.addLayer({
    id: 'tracts-line',
    type: 'line',
    source: 'tracts',
    'source-layer': 'tracts',
    paint: {
      'line-color': ['case', selected, COLORS.tractSelected, COLORS.tract],
      // Zoom must be the outermost expression, so the selected case sits inside each stop.
      'line-width': ['interpolate', ['linear'], ['zoom'], 12, ['case', selected, 2, 0.4], 17, ['case', selected, 3, 1.4]],
    },
  })
  map.addLayer({
    id: 'structures-fill',
    type: 'fill',
    source: 'structures',
    'source-layer': 'structures',
    paint: {
      'fill-color': ['case', selected, COLORS.structureSelected, COLORS.structure],
      'fill-opacity': 0.85,
    },
  })
  map.addLayer({
    id: 'structures-line',
    type: 'line',
    source: 'structures',
    'source-layer': 'structures',
    paint: {
      'line-color': COLORS.structureSelected,
      'line-width': ['case', selected, 2, 0.5],
    },
  })
}

const LAYER_IDS: Record<keyof LayerVisibility, string[]> = {
  imagery: ['imagery'],
  tracts: ['tracts-fill', 'tracts-line'],
  structures: ['structures-fill', 'structures-line'],
}

function featureId(selection: NonNullable<Selection>): FeatureIdentifier {
  const layer = selection.kind === 'tract' ? 'tracts' : 'structures'
  return { source: layer, sourceLayer: layer, id: selection.id }
}

export function MapView({ initialBbox, visible, selection, onSelect, onZoom }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)
  // Only the first value matters: it sets the opening view.
  const initialBboxRef = useRef(initialBbox)
  // Read inside map event handlers, which are bound once.
  const onSelectRef = useRef(onSelect)
  const onZoomRef = useRef(onZoom)
  useEffect(() => {
    onSelectRef.current = onSelect
    onZoomRef.current = onZoom
  })

  // Build the map once. `map` state is set only after our sources and layers exist, so the
  // effects below never touch a half-built map.
  useEffect(() => {
    if (!container.current) return
    const bbox = initialBboxRef.current
    const instance = new MapLibreMap({
      container: container.current,
      style: BASEMAP_STYLE,
      center: FALLBACK_CENTER,
      zoom: 11,
      maxZoom: 19,
      ...(bbox ? { bounds: bbox, fitBoundsOptions: { padding: 40, maxZoom: 15 } } : {}),
    })
    instance.addControl(new NavigationControl({ visualizePitch: false }), 'top-right')
    instance.addControl(new ScaleControl({ unit: 'imperial' }), 'bottom-right')

    let usingPlainStyle = false
    instance.on('error', (event) => {
      if (!usingPlainStyle && !instance.loaded() && String(event.error?.message).includes(BASEMAP_STYLE)) {
        console.warn('Basemap unavailable, falling back to a plain background')
        usingPlainStyle = true
        instance.setStyle(PLAIN_STYLE)
      }
    })

    instance.on('load', () => {
      // Draw our layers under the basemap's labels so place names stay readable.
      const firstLabel = instance.getStyle().layers.find((l) => l.type === 'symbol')?.id
      addDataLayers(instance)
      if (firstLabel) {
        for (const id of Object.values(LAYER_IDS).flat()) instance.moveLayer(id, firstLabel)
      }
      setMap(instance)
    })

    instance.on('zoomend', () => onZoomRef.current(instance.getZoom()))
    onZoomRef.current(instance.getZoom())

    instance.on('click', (event) => {
      const hits: MapGeoJSONFeature[] = instance.queryRenderedFeatures(event.point, {
        layers: ['structures-fill', 'tracts-fill'].filter((id) => instance.getLayer(id)),
      })
      // Buildings sit on top of lots, so a building hit wins.
      const hit = hits.find((f) => f.layer.id === 'structures-fill') ?? hits[0]
      if (!hit || typeof hit.id !== 'number') {
        onSelectRef.current(null)
        return
      }
      onSelectRef.current({ kind: hit.layer.id === 'structures-fill' ? 'structure' : 'tract', id: hit.id })
    })
    for (const id of ['structures-fill', 'tracts-fill']) {
      instance.on('mouseenter', id, () => (instance.getCanvas().style.cursor = 'pointer'))
      instance.on('mouseleave', id, () => (instance.getCanvas().style.cursor = ''))
    }

    return () => {
      setMap(null)
      instance.remove()
    }
  }, [])

  // Layer toggles.
  useEffect(() => {
    if (!map) return
    for (const [key, ids] of Object.entries(LAYER_IDS)) {
      const visibility = visible[key as keyof LayerVisibility] ? 'visible' : 'none'
      for (const id of ids) map.setLayoutProperty(id, 'visibility', visibility)
    }
  }, [map, visible])

  // Highlight the selection; feature ids come from the tiles (ST_AsMVT's feature_id_name).
  useEffect(() => {
    if (!map || !selection) return
    const id = featureId(selection)
    map.setFeatureState(id, { selected: true })
    return () => {
      // Skipped when the map itself is being torn down.
      if (map.getSource(id.source)) map.removeFeatureState(id, 'selected')
    }
  }, [map, selection])

  return <div ref={container} className="map" />
}
