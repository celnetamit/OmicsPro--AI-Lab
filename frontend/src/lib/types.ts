/** Shapes mirrored from the API. The two vocabularies stay separate here too. */

/** Scientific analysis track. Never expresses commercial permission. */
export type AnalysisTrack = 'foundation' | 'core' | 'advanced'

/** Commercial access tier. Never labels a scientific track. */
export type AccessTier = 'basic' | 'moderate' | 'expert'

export type InterpretationLabel =
  | 'supported'
  | 'partially_supported'
  | 'needs_validation'
  | 'speculative'

export interface Me {
  id: string
  email: string
  fullName: string
  isAdmin: boolean
  accessTier: AccessTier
  currentWeek: number | null
  programCode: string | null
  cohort: string | null
  activePhase: number
  /** True when this deployment opens without a sign-in. */
  openAccess: boolean
}

export interface FeatureRow {
  key: string
  label: string
  minTier: AccessTier
  unlocked: boolean
  available: boolean
  lockedExplanation: string
  phase: number
}

export interface EntitlementMatrix {
  currentTier: AccessTier
  currentTierLabel: string
  activePhase: number
  features: FeatureRow[]
  allowance: {
    runsPerModulePerWeek: number | null
    perturbationsPerRun: number
    parameterScope: string
    exportFormats: string[]
    maxUploadBytes: number
  }
}

export interface WeekRow {
  week: number
  focus: string
  module: string
  moduleLabel: string
  track: AnalysisTrack | null
  phase: number
  unlocked: boolean
  available: boolean
  status: string
}

/** Lifecycle of a run. Queued/validating/running still change on their own. */
export type RunStatus =
  | 'queued'
  | 'validating'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface RunSummary {
  id: string
  datasetId: string
  track: AnalysisTrack
  module: string
  week: number | null
  accessTier: AccessTier
  status: string
  pipelineVersion: string
  methodVersions: Record<string, string>
  parameters: Record<string, unknown>
  outputs: Record<string, Record<string, unknown>>
  lastValidStep: string | null
  nextStep: string | null
  errorMessage: string
  isOriginal: boolean
  parentRunId: string | null
  startedAt?: string | null
  finishedAt?: string | null
}

export interface ParameterDescriptor {
  key: string
  label: string
  step: string
  kind: string
  default: unknown
  methodRule: string
  caveat: string
  min: number | null
  max: number | null
  choices: unknown[] | null
  freeform: boolean
}

export interface EvidenceRef {
  id: string
  source_type: string
  title: string
  reference: string
  summary: string
}

export interface PerturbationOffer {
  key: string
  label: string
  parameterKey: string
  currentValue: number
  proposedValue: number
  scientificReason: string
  expectedConsequence: {
    metric: string
    metricLabel: string
    direction: string
    reason: string
  }[]
  whatToObserve: string
  limitation: string
  evidence: EvidenceRef[]
}
