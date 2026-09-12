/**
 * The NanoSchool Virtual Live Lab — Expert Review Form.
 *
 * Transcribed from the review form issued to reviewers.
 *
 * This file is a copy of src/lib/reviewForm.ts in the hub, kept identical. The
 * two repositories deploy separately and share no package, so a copy is the
 * honest description of the situation rather than a shortcut — and the fields
 * a reviewer fills in here are validated against the same definitions there.
 * If the form changes, both copies change together; a test asserts the shape
 * the endpoint expects.
 *
 * The wording of the severity definitions and the final-recommendation options
 * is the form's, not ours. It is reproduced rather than paraphrased: a reviewer
 * choosing "Recommended after Minor Corrections" is making a defined statement,
 * and softening the definition changes what they said.
 */

/* ---- Section A: overall assessment ---- */

export const RATING_VALUES = [
  "EXCELLENT",
  "GOOD",
  "NEEDS_IMPROVEMENT",
  "MAJOR_CONCERN",
  "NA",
] as const;
export type RatingValue = (typeof RATING_VALUES)[number];

export const RATING_LABELS: Record<RatingValue, string> = {
  EXCELLENT: "Excellent",
  GOOD: "Good",
  NEEDS_IMPROVEMENT: "Needs Improvement",
  MAJOR_CONCERN: "Major Concern",
  NA: "N/A",
};

export const REVIEW_AREAS = [
  { id: "SCIENTIFIC_ACCURACY", label: "Scientific / Technical Accuracy" },
  { id: "METHODOLOGY", label: "Methodology / Workflow" },
  { id: "DATASET_SUITABILITY", label: "Dataset / Input Suitability" },
  { id: "PARAMETERS", label: "Parameters / Assumptions" },
  { id: "CALCULATIONS", label: "Calculations / Computational Logic" },
  { id: "RESULTS", label: "Results & Visualisations" },
  { id: "INTERPRETATION", label: "Interpretation & Limitations" },
  { id: "REPRODUCIBILITY", label: "Reproducibility / Validation" },
  { id: "EDUCATIONAL_VALUE", label: "Educational Value" },
  { id: "USABILITY", label: "User Workflow / Usability" },
] as const;

export type ReviewAreaId = (typeof REVIEW_AREAS)[number]["id"];
export type Ratings = Partial<Record<ReviewAreaId, RatingValue>>;

/* ---- Section B: issues and recommendations ---- */

export const SEVERITIES = ["CRITICAL", "MAJOR", "MINOR", "SUGGESTION"] as const;
export type Severity = (typeof SEVERITIES)[number];

/** The form's own definitions, verbatim. */
export const SEVERITY_DEFINITIONS: Record<Severity, { label: string; definition: string }> = {
  CRITICAL: {
    label: "Critical",
    definition:
      "Scientific, safety, privacy, security or technical issue that should be resolved before release.",
  },
  MAJOR: {
    label: "Major",
    definition:
      "Important correction that significantly affects methodology, results, interpretation or learner experience.",
  },
  MINOR: {
    label: "Minor",
    definition: "Small correction that does not invalidate the workflow.",
  },
  SUGGESTION: {
    label: "Suggestion",
    definition: "Optional improvement or enhancement.",
  },
};

export interface ReviewIssue {
  /** "Lab Step / Module" on the form. */
  module: string;
  severity: Severity | "";
  observation: string;
  /** "Recommended Change / Reference". */
  recommendation: string;
}

/* ---- Section C: domain-specific checks ---- */

export const DOMAIN_CHECKS = [
  {
    id: "BIO",
    label: "Bio / Genomics / Medical",
    items: [
      { id: "BIO_DATA_TYPE", label: "Data type is appropriate" },
      { id: "BIO_INTERPRETATION", label: "Biological interpretation is scientifically justified" },
      { id: "BIO_STATS", label: "Statistical analysis is appropriate" },
      { id: "BIO_LIMITATIONS", label: "Dataset limitations are explained" },
      { id: "BIO_NO_CLINICAL", label: "No inappropriate clinical conclusions are presented" },
    ],
  },
  {
    id: "AI",
    label: "AI / Machine Learning",
    items: [
      { id: "AI_MODEL_SELECTION", label: "Model selection is appropriate" },
      { id: "AI_TRAIN_TEST", label: "Training/testing logic is valid" },
      { id: "AI_METRICS", label: "Performance metrics are appropriate" },
      {
        id: "AI_EXPLANATIONS_DISTINGUISHABLE",
        label: "AI-generated explanations are distinguishable from calculated results",
      },
      { id: "AI_BIAS", label: "Bias, uncertainty and limitations are communicated" },
    ],
  },
  {
    id: "NANO",
    label: "Nano / Materials / Engineering",
    items: [
      { id: "NANO_MODEL", label: "Scientific model is appropriate" },
      { id: "NANO_UNITS", label: "Parameters and units are correct" },
      { id: "NANO_ASSUMPTIONS", label: "Assumptions are transparent" },
      {
        id: "NANO_NOT_OVERSTATED",
        label: "Results are not overstated beyond computational/experimental evidence",
      },
      { id: "NANO_LIMITATIONS", label: "Limitations and validation requirements are explained" },
    ],
  },
  {
    id: "CYBER",
    label: "Cybersecurity",
    items: [
      { id: "CYBER_CONTAINED", label: "Activities are contained within the authorised environment" },
      { id: "CYBER_NO_EXPLOIT", label: "No unsafe real-world exploitation is enabled" },
      { id: "CYBER_ASSUMPTIONS", label: "Security assumptions are correctly explained" },
      { id: "CYBER_CREDENTIALS", label: "Sensitive data and credentials are appropriately protected" },
      { id: "CYBER_BOUNDARIES", label: "Responsible-use boundaries are clear" },
    ],
  },
] as const;

export type DomainId = (typeof DOMAIN_CHECKS)[number]["id"];
/** Checked item ids, per domain. Domains a reviewer skipped are simply absent. */
export type DomainChecks = Partial<Record<DomainId, string[]>>;

/* ---- Section D: final recommendation ---- */

export const RECOMMENDATIONS = [
  { id: "RELEASE", label: "Recommended for Release" },
  { id: "MINOR_CORRECTIONS", label: "Recommended after Minor Corrections" },
  { id: "MAJOR_CORRECTIONS", label: "Recommended after Major Corrections" },
  { id: "RE_REVIEW", label: "Re-review Recommended after Corrections" },
  { id: "NOT_RECOMMENDED", label: "Not Recommended for Release in Current Form" },
] as const;

export type RecommendationId = (typeof RECOMMENDATIONS)[number]["id"];

/* ---- The whole form ---- */

export interface ReviewSubmission {
  reviewerName: string;
  areaOfExpertise: string;
  versionBuild: string;
  reviewDate: string;
  ratings: Ratings;
  issues: ReviewIssue[];
  domainChecks: DomainChecks;
  finalRecommendation: RecommendationId | "";
  mostImportantCorrection: string;
  optionalSuggestions: string;
  reviewerComments: string;
}

export const REVIEW_STATUSES = ["DRAFT", "SUBMITTED"] as const;
export type ReviewStatus = (typeof REVIEW_STATUSES)[number];

export function isRatingValue(v: unknown): v is RatingValue {
  return typeof v === "string" && (RATING_VALUES as readonly string[]).includes(v);
}
export function isSeverity(v: unknown): v is Severity {
  return typeof v === "string" && (SEVERITIES as readonly string[]).includes(v);
}
export function isRecommendation(v: unknown): v is RecommendationId {
  return typeof v === "string" && RECOMMENDATIONS.some((r) => r.id === v);
}

/**
 * What a submission must have before it counts as complete.
 *
 * Only four things, and deliberately so. The domain checklists are explicitly
 * "complete only those relevant to your expertise", and the issues table is
 * empty for a lab a reviewer is happy with — requiring either would push
 * reviewers into inventing content to get past a validator, which is worse
 * than an incomplete form.
 */
export function missingRequired(form: ReviewSubmission): string[] {
  const missing: string[] = [];
  if (!form.reviewerName.trim()) missing.push("Reviewer name");
  if (!form.areaOfExpertise.trim()) missing.push("Area of expertise");
  if (!form.finalRecommendation) missing.push("Final recommendation");
  const rated = REVIEW_AREAS.filter((a) => form.ratings[a.id]).length;
  if (rated < REVIEW_AREAS.length) {
    missing.push(`All ten review areas (${rated} of ${REVIEW_AREAS.length} rated)`);
  }
  /*
   * The form asks for the most important correction as a heading of its own.
   * It is required only when the reviewer is asking for corrections — for a
   * clean "Recommended for Release" there is, by definition, nothing to put
   * there.
   */
  const wantsCorrections =
    form.finalRecommendation !== "" && form.finalRecommendation !== "RELEASE";
  if (wantsCorrections && !form.mostImportantCorrection.trim()) {
    missing.push("Most important correction before release");
  }
  return missing;
}
