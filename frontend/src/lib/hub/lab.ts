/**
 * What this lab calls itself when it talks to NanoSchool.
 *
 * The reviewer agreement and the review form both record which lab and which
 * build were reviewed, and both are read by someone comparing reviews across
 * labs. They are constants rather than free text on the form so that every
 * review of this lab files under the same name.
 */

export const LAB_TITLE = 'OmicsLab Pro — Single-cell and Spatial Transcriptomics Live Lab';

/** The domain checklist a reviewer of this lab works through first. */
export const LAB_DOMAIN = 'Bio / Genomics / Medical';

/**
 * The deployment's release stamp, the same one the footer shows. A review is
 * about a build, so a review that cannot name one is hard to act on later.
 */
export const BUILD_VERSION = import.meta.env.VITE_RELEASE ?? 'dev';
