/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BASEMAP_STYLE?: string
  readonly VITE_IMAGERY_TILES?: string
  readonly VITE_IMAGERY_ATTRIBUTION?: string
  readonly VITE_DEFAULT_CENTER?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
