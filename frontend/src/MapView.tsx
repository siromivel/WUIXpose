import {
  type ExpressionSpecification,
  type FeatureIdentifier,
  type FilterSpecification,
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

import type { Bbox, ZoneRing } from './api'
import { config } from './config'
import {
  type LayerVisibility,
  type Selection,
  TILE_LAYERS,
  type TileSources,
  ZONE_FALLBACK_COLOR,
  zoneColor,
} from './layers'

// MapLibre looks for its worker next to its own module file, which isn't where Vite puts
// either one. Let Vite bundle the worker and tell MapLibre where it went.
setWorkerUrl(maplibreWorkerUrl)

// A point to fly to. Each new object flies again, even to the same point.
export interface Focus {
  lon: number
  lat: number
}

interface Props {
  initialBbox: Bbox | null
  tileSources: TileSources
  zoneRings: ZoneRing[]
  visible: LayerVisibility
  focus: Focus | null
  selection: Selection
  onSelect: (selection: Selection) => void
  onZoom: (zoom: number) => void
}

// Used if the basemap can't be fetched, so lots and structures still draw on a plain ground.
const PLAIN_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#eceee8' } }],
}
const COLORS = {
  tract: '#3d5a80',
  tractSelected: '#1d3557',
  structure: '#e07a2f',
  structureSelected: '#9d2d0f',
  zonesSelected: '#1d2733',
}

const selected: ExpressionSpecification = ['boolean', ['feature-state', 'selected'], false]

// A value chosen by the feature's ring, as a style expression.
function byRing<T extends string | number>(
  rings: ZoneRing[],
  value: (ring: ZoneRing, index: number) => T,
  fallback: T,
): ExpressionSpecification {
  return rings.reduceRight<ExpressionSpecification>(
    (otherwise, ring, i) => ['case', ['==', ['get', 'ring_key'], ring.key], value(ring, i), otherwise],
    ['literal', fallback],
  )
}

// Zones of neighboring structures overlap, and the ring nearer its own structure ranks higher:
// a spot 5 ft from one building and 50 ft from another is zone 1. A ring the server didn't
// list ranks lowest.
const ringRank = (rings: ZoneRing[]) => byRing(rings, (_, i) => rings.length - i, 0)
// Meters. Enough to order the rings in the depth buffer, too little to see when the map is tilted.
const ZONE_SLAB_STEP = 0.25
// Close enough to see a house's zones and its neighbors'.
const FOCUS_ZOOM = 17

// Zones belonging to the selection: a structure's own, or those of every structure on a lot.
function zonesOf(selection: Selection): FilterSpecification {
  if (!selection) return false
  return ['==', ['get', selection.kind === 'structure' ? 'structure_id' : 'tract_id'], selection.id]
}

function addDataLayers(map: MapLibreMap, tileSources: TileSources, zoneRings: ZoneRing[]) {
  map.addSource('imagery', {
    type: 'raster',
    tiles: [config.imageryTiles],
    tileSize: 256,
    maxzoom: 16,
    attribution: config.imageryAttribution,
  })
  map.addLayer({
    id: 'imagery',
    type: 'raster',
    source: 'imagery',
    layout: { visibility: 'none' },
  })

  // Tile URLs, zoom range and attribution all come from the server's TileJSON.
  for (const layer of TILE_LAYERS) {
    const { tiles, minzoom, maxzoom, attribution } = tileSources[layer]
    map.addSource(layer, { type: 'vector', tiles, minzoom, maxzoom, attribution })
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
      'line-width': [
        'interpolate',
        ['linear'],
        ['zoom'],
        12,
        ['case', selected, 2, 0.4],
        17,
        ['case', selected, 3, 1.4],
      ],
    },
  })
  // The shading says which zone the ground is in, so it is the same however many structures'
  // rings cover a spot, and where different rings overlap the higher-ranked one shows alone. A
  // fill layer can't do that: its overlapping features always blend. A fill-extrusion layer
  // applies its opacity to the layer as a whole and colors only the topmost surface, so the
  // rings are drawn as slabs, higher-ranked ones slightly taller.
  map.addLayer({
    id: 'zones-fill',
    type: 'fill-extrusion',
    source: 'zones',
    'source-layer': 'zones',
    paint: {
      'fill-extrusion-color': byRing(zoneRings, zoneColor, ZONE_FALLBACK_COLOR),
      'fill-extrusion-height': ['*', ringRank(zoneRings), ZONE_SLAB_STEP],
      'fill-extrusion-opacity': 0.3,
    },
  })
  // Extrusions are shaded by the style's light, which brightens dark colors; with no intensity
  // the zones stay the colors the legend shows.
  map.setLight({ anchor: 'viewport', intensity: 0 })
  // The ground the selection's zones cover, darkened so it stands out among its neighbors'. One
  // neutral color at one height, so it darkens evenly and leaves each zone's color as it was;
  // above every zone slab, because extrusion layers share a depth buffer and a lower one would
  // be hidden by them.
  map.addLayer({
    id: 'zones-selected-fill',
    type: 'fill-extrusion',
    source: 'zones',
    'source-layer': 'zones',
    filter: zonesOf(null),
    paint: {
      'fill-extrusion-color': COLORS.zonesSelected,
      'fill-extrusion-height': (zoneRings.length + 1) * ZONE_SLAB_STEP,
      'fill-extrusion-opacity': 0.25,
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

// Listed bottom to top: this order is the drawing order once the layers are moved under the
// basemap's labels.
const LAYER_IDS: Record<keyof LayerVisibility, string[]> = {
  imagery: ['imagery'],
  tracts: ['tracts-fill', 'tracts-line'],
  zones: ['zones-fill', 'zones-selected-fill'],
  structures: ['structures-fill', 'structures-line'],
}

function featureId(selection: NonNullable<Selection>): FeatureIdentifier {
  const layer = selection.kind === 'tract' ? 'tracts' : 'structures'
  return { source: layer, sourceLayer: layer, id: selection.id }
}

export function MapView({ initialBbox, tileSources, zoneRings, visible, focus, selection, onSelect, onZoom }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)
  // Only the first values matter: they set the opening view, the sources and their styling.
  const initialBboxRef = useRef(initialBbox)
  const tileSourcesRef = useRef(tileSources)
  const zoneRingsRef = useRef(zoneRings)
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
      style: config.basemapStyle,
      center: config.defaultCenter,
      zoom: 11,
      maxZoom: 19,
      ...(bbox ? { bounds: bbox, fitBoundsOptions: { padding: 40, maxZoom: 15 } } : {}),
    })
    instance.addControl(new NavigationControl({ visualizePitch: false }), 'top-right')
    instance.addControl(new ScaleControl({ unit: 'imperial' }), 'bottom-right')

    let usingPlainStyle = false
    instance.on('error', (event) => {
      if (!usingPlainStyle && !instance.loaded() && String(event.error?.message).includes(config.basemapStyle)) {
        console.warn('Basemap unavailable, falling back to a plain background')
        usingPlainStyle = true
        instance.setStyle(PLAIN_STYLE)
      }
    })

    instance.on('load', () => {
      // Draw our layers under the basemap's labels so place names stay readable.
      const firstLabel = instance.getStyle().layers.find((l) => l.type === 'symbol')?.id
      addDataLayers(instance, tileSourcesRef.current, zoneRingsRef.current)
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
      onSelectRef.current({
        kind: hit.layer.id === 'structures-fill' ? 'structure' : 'tract',
        id: hit.id,
      })
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

  useEffect(() => {
    if (map) map.setFilter('zones-selected-fill', zonesOf(selection))
  }, [map, selection])

  // Keep the zoom if already closer in.
  useEffect(() => {
    if (map && focus) map.flyTo({ center: [focus.lon, focus.lat], zoom: Math.max(map.getZoom(), FOCUS_ZOOM) })
  }, [map, focus])

  return <div ref={container} className="map" />
}
