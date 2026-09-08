/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Deployment stamp, injected at build time (see frontend/Dockerfile). */
  readonly VITE_RELEASE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
