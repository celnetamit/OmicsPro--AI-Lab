import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get } from '../lib/api'
import { Band, EmptyState, PageHeader, SectionHead, Skeleton, StatusPill } from '../components/ui'
import { TRACK_NAME, named } from '../lib/labels'
import { TRACK_ICONS } from '../components/icons'
import { useSession } from '../components/Session'
import type { FeatureRow, RunSummary, WeekRow } from '../lib/types'

interface Home {
  currentWeek: number
  accessTier: string
  weeks: WeekRow[]
  availableTracks: { track: string; label: string }[]
  recentRuns: RunSummary[]
  hasDesignPlan: boolean
  lockedFeatures: FeatureRow[]
}

/** The tier enum, as a word: 'moderate' -> 'Moderate'. */
const TIER_WORD = (tier: string) => tier.charAt(0).toUpperCase() + tier.slice(1)

/** One line on what each track actually does, for the feature grid. */
const TRACK_BLURB: Record<string, string> = {
  foundation:
    'Bulk RNA-seq: sample-aware differential expression and pathway interpretation on a real published design.',
  core:
    'Single-cell RNA-seq: quality control, integration, clustering and annotation, with every threshold recorded.',
  advanced:
    'Spatial transcriptomics: tissue-aware clustering and neighbourhood analysis, optionally mapped to a single-cell reference.',
}

const STATUS_TEXT: Record<string, string> = {
  open: 'Open',
  locked_until_week: 'Opens later in the program',
  scheduled_for_later_release: 'Scheduled for a later release',
}

export function LabHome() {
  const { matrix } = useSession()
  const [home, setHome] = useState<Home | null>(null)

  useEffect(() => {
    void get<Home>('/api/program/home').then(setHome)
  }, [])

  if (!home) {
    return (
      <>
        <PageHeader title="Lab Home" />
        <Skeleton lines={4} />
        <span className="visually-hidden" role="status">
          Loading
        </span>
      </>
    )
  }

  return (
    <>
      <PageHeader
        hero
        title="Single-cell and spatial transcriptomics, run for real"
        lede="Analysis you can reconstruct, defend and carry into your capstone."
      />

      <Band>
        <div className="lede-row">
          <div>
            <span className="tag">Week {home.currentWeek} of eight</span>
            <h3 className="mt-4">Where you are</h3>
          </div>
          <div className="row">
            <Link className="button" to="/datasets">
              Start an analysis
            </Link>
            <Link className="button secondary" to="/knowledge-bank">
              Knowledge Bank
            </Link>
          </div>
        </div>
        <div className="metrics mt-5">
          <div className="metric">
            <div className="value">{home.weeks.filter((w) => w.status === 'open').length}/8</div>
            <div className="name">Modules open to you</div>
          </div>
          <div className="metric">
            <div className="value">{home.availableTracks.length}</div>
            <div className="name">Analysis tracks</div>
          </div>
          <div className="metric">
            <div className="value">{home.recentRuns.length}</div>
            <div className="name">Runs on record</div>
          </div>
          <div className="metric">
            <div className="value">{matrix?.currentTierLabel ?? '—'}</div>
            <div className="name">Access tier</div>
          </div>
        </div>
      </Band>

      <Band tint>
        <SectionHead
          title="Program progress"
          sub="Eight weeks, each opening its own Live Lab module."
        />
        <div className="card">
          <div className="scroll">
          <table className="stacked">
            <thead>
              <tr>
                <th>Week</th>
                <th>Focus</th>
                <th>Live Lab module</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {home.weeks.map((week) => (
                <tr key={week.week}>
                  <td data-label="Week">{week.week}</td>
                  <td data-label="Focus">{week.focus}</td>
                  <td data-label="Module">{week.moduleLabel}</td>
                  <td data-label="Status">{STATUS_TEXT[week.status] ?? week.status}</td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        </div>
      </Band>

      <Band>
        <SectionHead
          centred
          title="Analysis tracks open to you"
          sub="Track names describe the science being done. They are separate from your access tier, which describes what you may run and export."
        />
        <div className="grid">
        {home.availableTracks.map((track) => (
          <div className="card interactive" key={track.track}>
            <span className="icon-tile">{TRACK_ICONS[track.track] ?? TRACK_ICONS.default}</span>
            <h3>{track.label}</h3>
            <p className="hint">{TRACK_BLURB[track.track] ?? ''}</p>
            <Link className="arrow-link mt-4" to="/datasets">
              Choose a dataset
            </Link>
          </div>
          ))}
        </div>
      </Band>

      <Band tint>
        <SectionHead title="Your week 1 work" sub="Both are open now." />
        <div className="grid-2">
        <div className="card">
          <h3>Week 1 design plan</h3>
          <p className="hint">
            {home.hasDesignPlan
              ? 'Your Experimental Design and Metadata Plan is saved to your portfolio.'
              : 'You have not saved a design plan yet. The plan is where replication, batch structure and confounders get decided — before any data is touched.'}
          </p>
          <Link className="button secondary mt-4" to="/design-studio">
            Open the Design Studio
          </Link>
        </div>

        <div className="card">
          <h3>Pre-Lab Assessment</h3>
          <p className="hint">
            Check what you already know before the guided walkthrough, so the Copilot's
            explanations land where they are actually needed.
          </p>
          <Link className="button secondary mt-4" to="/pre-lab">
            Take the assessment
          </Link>
          </div>
        </div>
      </Band>

      <Band>
        <SectionHead
          title="Recent runs"
          action={
            <Link className="arrow-link" to="/runs">
              View all runs
            </Link>
          }
        />
        <div className="card">
        {home.recentRuns.length === 0 ? (
          <EmptyState
            title="No analyses run yet"
            action={
              <Link className="button secondary" to="/datasets">
                Open the Dataset Selector
              </Link>
            }
          >
            Your runs will appear here with their status, track and pipeline version.
          </EmptyState>
        ) : (
          <div className="scroll">
          <table className="stacked">
            <thead>
              <tr>
                <th>Run</th>
                <th>Track</th>
                <th>Status</th>
                <th>Kind</th>
              </tr>
            </thead>
            <tbody>
              {home.recentRuns.map((run) => (
                <tr key={run.id}>
                  <td data-label="Run">
                    <Link className="mono" to={`/runs/${run.id}`}>
                      {run.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td data-label="Track">{named(TRACK_NAME, run.track)}</td>
                  <td data-label="Status">
                    <StatusPill status={run.status} />
                  </td>
                  <td data-label="Kind">{run.isOriginal ? 'Original' : 'Alternate settings'}</td>
                </tr>
              ))}
              </tbody>
              </table>
            </div>
          )}
        </div>
      </Band>

      {home.lockedFeatures.length ? (
        <Band tint>
          <SectionHead
            title="Available with a paid upgrade"
            sub="Every locked capability is listed here with the reason it is locked. Nothing is hidden from you — the teaching content of every week is included at every tier."
            action={
              <Link className="arrow-link" to="/upgrade">
                Compare access options
              </Link>
            }
          />
          <div className="grid">
            {home.lockedFeatures.map((feature) => (
              <div className="card" key={feature.key}>
                <span className="tag neutral">{TIER_WORD(feature.minTier)} access</span>
                <h3 className="mt-4">{feature.label}</h3>
                <p className="hint">{feature.lockedExplanation}</p>
              </div>
            ))}
          </div>
        </Band>
      ) : null}

      <Band accent>
        <h3>Take the next analysis further</h3>
        <p>
          Paid tiers add depth, repetition and independence: your own parameters, your
          own datasets, the full spatial workflow and the capstone workspace.
        </p>
        <Link className="button" to="/upgrade">
          Compare access options
        </Link>
      </Band>
    </>
  )
}
