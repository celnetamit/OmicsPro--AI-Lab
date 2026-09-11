/**
 * Words for the platform's machine keys.
 *
 * The API speaks in keys (`pdf_summary`, `pending_data_ingest`, `core`); a
 * learner reads words. Every screen that shows one of these keys goes through
 * here, so a key is named the same way everywhere it appears.
 */

export const TRACK_LABEL: Record<string, string> = {
  foundation: 'Foundation — Bulk RNA-seq',
  core: 'Core — Single-cell RNA-seq',
  advanced: 'Advanced — Spatial Transcriptomics',
}

/** The track's own name, for table cells where the full label would crowd. */
export const TRACK_NAME: Record<string, string> = {
  foundation: 'Foundation',
  core: 'Core',
  advanced: 'Advanced',
}

export const TIER_LABEL: Record<string, string> = {
  basic: 'Basic',
  moderate: 'Moderate',
  expert: 'Expert',
}

export const KIND_LABEL: Record<string, string> = {
  guided: 'Guided',
  trial: 'Trial',
  upload: 'Your upload',
}

export const EXPORT_LABEL: Record<string, string> = {
  pdf_summary: 'Summary PDF',
  pdf_full: 'Full PDF report',
  csv: 'CSV tables',
  figure_pack: 'Figure pack',
  slides: 'Slide deck',
  raw_objects: 'Analysis objects',
}

export const VALIDATION_LABEL: Record<string, string> = {
  validated: 'Validated',
  pending: 'Pending validation',
  pending_data_ingest: 'Awaiting data ingest',
  failed_validation: 'Failed validation',
}

/** Pipeline steps by key; anything missing falls back to its key in words. */
export const STEP_LABEL: Record<string, string> = {
  validate: 'Validation',
  qc: 'Quality control',
  cell_qc: 'Cell quality control',
  filter: 'Filtering',
  exploratory: 'Sample structure',
  feature_selection: 'Normalisation and variable genes',
  dimensionality_reduction: 'Principal components',
  neighborhood_graph: 'Neighbourhood graph',
  embedding: 'UMAP layout',
  clustering: 'Clustering',
  marker_genes: 'Marker genes',
  composition: 'Composition',
  differential_expression: 'Differential expression',
  pathway_analysis: 'Pathway enrichment',
  communication: 'Cell-cell communication',
}

export const COPILOT_FUNCTION_LABEL: Record<string, string> = {
  explain: 'Explanation',
  interpret: 'Interpretation',
  challenge: 'Challenge',
  recommend: 'Recommendation',
  evidence: 'Evidence',
  suggest_perturbation: 'What-if suggestion',
  dataset_brief: 'Dataset explanation',
}

/** A key with no entry in a map, as words: `region_comparison` → "Region comparison". */
export function humanise(key: string | null | undefined): string {
  if (!key) return '—'
  const words = key.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function named(map: Record<string, string>, key: string | null | undefined): string {
  return key ? map[key] ?? humanise(key) : '—'
}

export function plural(n: number, noun: string, many = `${noun}s`): string {
  return `${n} ${n === 1 ? noun : many}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}
