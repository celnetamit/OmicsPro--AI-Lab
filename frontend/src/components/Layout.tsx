import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useHubSession } from './HubSession'
import { leaveLab } from '../lib/labAuth'
import { useSession } from './Session'
import { ReportIssue } from './ReportIssue'
import { ThemeToggle } from './ThemeToggle'

/** The thirteen screens, grouped as they are in the program itself. */
const NAV: { label: string; items: { to: string; label: string; end?: boolean }[] }[] = [
  {
    label: 'Program',
    items: [
      { to: '/knowledge-bank', label: 'Knowledge Bank' },
      { to: '/pre-lab', label: 'Pre-Lab Assessment' },
      { to: '/design-studio', label: 'Experimental Design Studio' },
    ],
  },
  {
    label: 'Analysis',
    items: [
      { to: '/datasets', label: 'Dataset Selector' },
      { to: '/upload', label: 'Upload a Dataset' },
      { to: '/runs', label: 'Analysis Workspace' },
      { to: '/compare', label: 'Compare Runs' },
    ],
  },
  {
    label: 'Record',
    items: [
      { to: '/capstone', label: 'Capstone Workspace' },
      { to: '/assessment', label: 'Assessment' },
      { to: '/reports', label: 'Report and Portfolio' },
    ],
  },
]

const RELEASE = import.meta.env.VITE_RELEASE ?? 'dev'

export function Layout() {
  const { me, matrix } = useSession()
  //: Governance belongs to NanoSchool rather than to this lab. Feedback is for
  //: everyone; the reviewer screens appear only for an account NanoSchool marks
  //: as a reviewer, which is a courtesy rather than the gate — the screens and
  //: the hub both check for themselves.
  const { identity } = useHubSession()
  const nav = [
    ...NAV,
    {
      label: 'Governance',
      items: [
        { to: '/feedback', label: 'Send feedback' },
        ...(identity?.isReviewer
          ? [
              { to: '/reviewer-agreement', label: 'Reviewer agreement' },
              { to: '/expert-review', label: 'Expert review form' },
            ]
          : []),
      ],
    },
  ]
  const location = useLocation()
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const barRef = useRef<HTMLElement>(null)

  //: Following a link should reveal the destination, not leave a menu over it.
  useEffect(() => {
    setOpenMenu(null)
    setNavOpen(false)
  }, [location.pathname])

  //: A menu closes on Escape and on a click anywhere outside the bar, which is
  //: what every other menu on the web does.
  useEffect(() => {
    if (!openMenu) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenMenu(null)
    }
    const onClick = (event: MouseEvent) => {
      if (!barRef.current?.contains(event.target as Node)) setOpenMenu(null)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [openMenu])

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>

      <header className="topnav" ref={barRef}>
        <div className="brand">
          <NavLink to="/" className="brand-mark" aria-label="OmicsLab Pro, Lab Home">
            OL
          </NavLink>
          <span className="brand-text">
            <span className="brand-name">OmicsLab Pro</span>
            <span className="brand-sub">NanoSchool Live Lab</span>
          </span>
        </div>

        <nav className={`topnav-links${navOpen ? ' open' : ''}`} id="primary-nav" aria-label="Primary">
          <NavLink to="/" end>
            Lab Home
          </NavLink>

          {nav.map((group) => {
            const current = group.items.some((item) => location.pathname.startsWith(item.to))
            const open = openMenu === group.label
            return (
              <div
                key={group.label}
                className={`topnav-menu${open ? ' open' : ''}${current ? ' current' : ''}`}
              >
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setOpenMenu(open ? null : group.label)}
                >
                  {group.label}
                </button>
                {open ? (
                  <div className="topnav-panel">
                    {group.items.map((item) => (
                      <NavLink key={item.to} to={item.to}>
                        {item.label}
                      </NavLink>
                    ))}
                  </div>
                ) : null}
              </div>
            )
          })}

          <NavLink to="/upgrade">Access</NavLink>
          {me?.isAdmin ? <NavLink to="/admin">Admin</NavLink> : null}
        </nav>

        <div className="topnav-actions">
          <span className="tier-chip">
            <span className="dot" aria-hidden="true" />
            {matrix?.currentTierLabel ?? '—'}
            {me?.currentWeek ? ` · week ${me.currentWeek}` : ''}
          </span>
          <ThemeToggle />
          {/* One control, because on a shared machine the useful action is both:
              leave the lab and leave nothing behind. The work stays on the
              server and the next launch picks it up. */}
          <button
            type="button"
            className="secondary small tip"
            data-tip="Ends this session and returns to live-labs.org"
            onClick={leaveLab}
          >
            Leave lab
          </button>
          <button
            type="button"
            className="secondary small nav-toggle"
            aria-expanded={navOpen}
            aria-controls="primary-nav"
            onClick={() => setNavOpen((value) => !value)}
          >
            {navOpen ? 'Close' : 'Menu'}
          </button>
        </div>
      </header>

      <main id="main" tabIndex={-1}>
        <div className="container">
          <Outlet />
        </div>
      </main>

      <footer className="site-foot">
        <div className="inner">
          <span>
            OmicsLab Pro — a{' '}
            <a
              className="tip"
              href="https://live-labs.org/"
              target="_blank"
              rel="noopener noreferrer"
              data-tip="live-labs.org — opens in a new tab"
            >
              Live Lab
            </a>{' '}
            for NanoSchool's eight-week single-cell and spatial transcriptomics program.
          </span>
          <span className="release-stamp">
            <ReportIssue /> ·{' '}
            {me?.authSource === 'local' ? 'Local session · ' : ''}Release {RELEASE}
          </span>
        </div>
      </footer>
    </div>
  )
}
