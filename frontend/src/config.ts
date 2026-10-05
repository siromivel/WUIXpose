// Deployment settings, read from VITE_* environment variables at build time (see .env.example).
// Anything about the app's own tiles comes from the server's TileJSON instead.

const env = import.meta.env

function lonLat(value: string | undefined, fallback: [number, number]): [number, number] {
  if (!value) return fallback
  const parts = value.split(',').map(Number)
  if (parts.length !== 2 || parts.some(Number.isNaN)) {
    throw new Error(`Expected "lon,lat", got ${JSON.stringify(value)}`)
  }
  return [parts[0], parts[1]]
}

export const config = {
  // Vector basemap style. Default: OpenFreeMap Positron, free and keyless (https://openfreemap.org).
  basemapStyle: env.VITE_BASEMAP_STYLE ?? 'https://tiles.openfreemap.org/styles/positron',

  // Raster imagery layer. Default: USGS National Map orthoimagery, public domain.
  imageryTiles:
    env.VITE_IMAGERY_TILES ??
    'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}',
  imageryAttribution:
    env.VITE_IMAGERY_ATTRIBUTION ??
    'Imagery: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS</a>',

  // Where the map opens when no data is loaded yet. Default: Boulder County foothills.
  defaultCenter: lonLat(env.VITE_DEFAULT_CENTER, [-105.35, 40.05]),
} as const
