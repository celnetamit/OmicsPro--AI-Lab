import { Suspense, lazy } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Layout } from './components/Layout'
import { SessionProvider, useSession } from './components/Session'
import { Skeleton } from './components/ui'
import { LabHome } from './pages/LabHome'
import { Login } from './pages/Login'

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
  if (!me) return <Login />

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
        <SessionProvider>
          <Routed />
        </SessionProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
