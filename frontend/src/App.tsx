import { Suspense, lazy } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Layout } from './components/Layout'
import { HubSessionProvider } from './components/HubSession'
import { LabAuthGuard } from './components/LabAuthGuard'
import { ReviewerAgreementGate } from './components/ReviewerAgreementGate'
import { SessionProvider, useSession } from './components/Session'
import { Skeleton } from './components/ui'
import { LabHome } from './pages/LabHome'

/**
 * The thirteen screens of spec 9, each a first-class route.
 *
 * Lab Home ships in the entry bundle because every session lands there; the
 * rest are split out so a learner working through week 1 never downloads the
 * capstone or admin screens.
 */
const KnowledgeBank = lazy(() => import('./pages/KnowledgeBank').then((m) => ({ default: m.KnowledgeBank })))
const PreLab = lazy(() => import('./pages/PreLab').then((m) => ({ default: m.PreLab })))
const DesignStudio = lazy(() => import('./pages/DesignStudio').then((m) => ({ default: m.DesignStudio })))
const Datasets = lazy(() => import('./pages/Datasets').then((m) => ({ default: m.Datasets })))
const DatasetInspector = lazy(() => import('./pages/DatasetInspector').then((m) => ({ default: m.DatasetInspector })))
const Upload = lazy(() => import('./pages/Upload').then((m) => ({ default: m.Upload })))
const RunList = lazy(() => import('./pages/RunList').then((m) => ({ default: m.RunList })))
const Workspace = lazy(() => import('./pages/Workspace').then((m) => ({ default: m.Workspace })))
const CompareRuns = lazy(() => import('./pages/CompareRuns').then((m) => ({ default: m.CompareRuns })))
const Capstone = lazy(() => import('./pages/Capstone').then((m) => ({ default: m.Capstone })))
const Assessment = lazy(() => import('./pages/Assessment').then((m) => ({ default: m.Assessment })))
const Reports = lazy(() => import('./pages/Reports').then((m) => ({ default: m.Reports })))
const Upgrade = lazy(() => import('./pages/Upgrade').then((m) => ({ default: m.Upgrade })))
const Admin = lazy(() => import('./pages/Admin').then((m) => ({ default: m.Admin })))
//: NanoSchool's own screens: feedback to the programme team, and the reviewer
//: agreement and review form a pre-release expert works through.
const Feedback = lazy(() => import('./pages/Feedback').then((m) => ({ default: m.Feedback })))
const ReviewerAgreement = lazy(() =>
  import('./pages/ReviewerAgreement').then((m) => ({ default: m.ReviewerAgreement })),
)
const ExpertReview = lazy(() => import('./pages/ExpertReview').then((m) => ({ default: m.ExpertReview })))

function NotFound() {
  return (
    <div className="empty">
      <h1>That screen does not exist</h1>
      <p>The address may have been mistyped, or the link may be from an older release.</p>
      <a className="button secondary" href="/">Back to Lab Home</a>
    </div>
  )
}

function Routed() {
  const { me, loading } = useSession()

  if (loading) {
    return (
      <div style={{ padding: 32, maxWidth: 640 }}>
        <Skeleton lines={4} />
        <span className="visually-hidden" role="status">Loading your session</span>
      </div>
    )
  }
  if (!me) {
    //: The gate let this session through and the server then refused to
    //: describe it — something other than an expired token, which LabAuthGuard
    //: handles by offering a relaunch. Nothing useful can render without a
    //: profile, so say that plainly instead of showing empty screens.
    return (
      <div className="empty">
        <h1>Could not load your session</h1>
        <p>
          The lab could not read your profile. Reload the page; if it keeps happening,
          launch the lab again from your NanoSchool dashboard.
        </p>
        <button type="button" onClick={() => window.location.reload()}>Reload</button>
      </div>
    )
  }

  return (
    <Suspense fallback={<div style={{ padding: 32 }}><Skeleton lines={4} /></div>}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<LabHome />} />
          <Route path="knowledge-bank" element={<KnowledgeBank />} />
          <Route path="pre-lab" element={<PreLab />} />
          <Route path="design-studio" element={<DesignStudio />} />
          <Route path="datasets" element={<Datasets />} />
          <Route path="datasets/:datasetId" element={<DatasetInspector />} />
          <Route path="upload" element={<Upload />} />
          <Route path="runs" element={<RunList />} />
          <Route path="runs/:runId" element={<Workspace />} />
          <Route path="compare" element={<CompareRuns />} />
          <Route path="capstone" element={<Capstone />} />
          <Route path="assessment" element={<Assessment />} />
          <Route path="reports" element={<Reports />} />
          <Route path="upgrade" element={<Upgrade />} />
          <Route path="admin" element={<Admin />} />
          <Route path="feedback" element={<Feedback />} />
          <Route path="reviewer-agreement" element={<ReviewerAgreement />} />
          <Route path="expert-review" element={<ExpertReview />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        {/* Nothing below this renders until NanoSchool has vouched for the
            visitor, and the session provider below it never creates a session
            of its own — so there is exactly one way into the lab. */}
        <LabAuthGuard>
          <SessionProvider>
            <HubSessionProvider>
              {/* An expert reviewer signs the agreement before any of the lab
                  renders; everyone else passes straight through. */}
              <ReviewerAgreementGate>
                <Routed />
              </ReviewerAgreementGate>
            </HubSessionProvider>
          </SessionProvider>
        </LabAuthGuard>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
