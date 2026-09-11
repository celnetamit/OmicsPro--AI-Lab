/**
 * Plots drawn from a run's recorded outputs (spec 5, 10.7).
 *
 * Every figure is drawn at its container's measured width, has a hover layer,
 * and has a table view — the table is how a value is reached without a pointer
 * and without relying on colour. Colours are theme tokens (see styles.css,
 * "chart tokens"), validated against both card surfaces.
 *
 * Deliberate choices, from the data-visualisation rules:
 *  - One series is one colour. Bars are never ramp-coloured by size.
 *  - UMAP clusters and spatial domains are not given a hue each: past three
 *    categories a scatter cannot keep every pair distinguishable. Cells are one
 *    series, clusters are labelled at their centroid, and selecting one
 *    highlights it over the rest in grey (the emphasis pattern). Domains are
 *    shown as small multiples, one map per domain, because a domain can be
 *    fragmented and a centroid label would sit outside it.
 *  - Differential expression uses the blue <-> red diverging pair: direction is
 *    polarity, and "not significant" is neutral grey.
 *  - Gene expression on tissue is one hue whose strength carries magnitude.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export interface FigureSpec {
  id: string
  label: string
  kind: string
  caption: string
  data: any
  context?: Record<string, any>
}

const SERIES = Array.from({ length: 8 }, (_, i) => `var(--viz-${i + 1})`)

/* ------------------------------------------------------------------ utils -- */
function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    observer.observe(node)
    setWidth(Math.floor(node.getBoundingClientRect().width))
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

/** Round an axis maximum up to a clean tick step. */
function niceTicks(max: number, count = 4): number[] {
  if (!(max > 0)) return [0]
  const raw = max / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw
  const ticks: number[] = []
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(Number(v.toFixed(10)))
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step)
  return ticks
}

function fmt(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (abs >= 1e4) return `${(value / 1e3).toFixed(1)}K`
  if (Number.isInteger(value)) return value.toLocaleString()
  if (abs > 0 && abs < 0.001) return value.toExponential(1)
  return value.toFixed(digits)
}

/** A bar whose data end is rounded and whose baseline end stays square. */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

type Tip = { x: number; y: number; body: ReactNode } | null
type TipFn = (event: React.MouseEvent, body: ReactNode) => void

/* ----------------------------------------------------------------- figure -- */
export function Figure({ figure }: { figure: FigureSpec }) {
  const [asTable, setAsTable] = useState(false)
  const [tip, setTip] = useState<Tip>(null)
  const frame = useRef<HTMLDivElement>(null)

  const showTip: TipFn = (event, body) => {
    const box = frame.current?.getBoundingClientRect()
    if (!box) return
    setTip({ x: event.clientX - box.left, y: event.clientY - box.top, body })
  }
  const hideTip = () => setTip(null)

  //: A summary is already a set of numbers: it has no separate table view.
  const tableable = figure.kind !== 'summary'

  return (
    <section className="figure" aria-label={figure.label}>
      <div className="figure-head">
        <div>
          <h4>{figure.label}</h4>
          <p className="hint">{figure.caption}</p>
        </div>
        {tableable ? (
          <div className="segmented" role="group" aria-label="View as">
            <button type="button" aria-pressed={!asTable} onClick={() => { hideTip(); setAsTable(false) }}>
              Chart
            </button>
            <button type="button" aria-pressed={asTable} onClick={() => { hideTip(); setAsTable(true) }}>
              Table
            </button>
          </div>
        ) : null}
      </div>

      <div className="viz" ref={frame} onMouseLeave={hideTip}>
        {asTable ? (
          <FigureTable figure={figure} />
        ) : (
          <FigureBody figure={figure} onTip={showTip} onTipEnd={hideTip} />
        )}
        {tip ? (
          <div
            className="viz-tip"
            role="status"
            style={{ left: tip.x, top: tip.y }}
          >
            {tip.body}
          </div>
        ) : null}
      </div>
    </section>
  )
}

function FigureBody({ figure, onTip, onTipEnd }: { figure: FigureSpec; onTip: TipFn; onTipEnd: () => void }) {
  const { kind, data, context = {} } = figure
  switch (kind) {
    case 'summary':
      return <SummaryTiles data={data} />
    case 'bar':
      return (
        <BarChart
          values={data as number[]}
          labels={(data as number[]).map((_, i) => (figure.id === 'library_sizes' ? `S${i + 1}` : String(i)))}
          valueName={figure.id === 'cluster_sizes' ? 'cells' : 'counts'}
          categoryName={figure.id === 'cluster_sizes' ? 'Cluster' : 'Sample'}
          onTip={onTip}
          onTipEnd={onTipEnd}
        />
      )
    case 'line':
      return <ScreeChart values={data as number[]} onTip={onTip} onTipEnd={onTipEnd} />
    case 'embedding':
      return <Embedding x={data.x} y={data.y} membership={context.membership} onTip={onTip} />
    case 'stacked_bar':
      return <StackedBar proportions={data} onTip={onTip} onTipEnd={onTipEnd} />
    case 'volcano':
      return <Volcano rows={data} fdr={context.fdr ?? 0.05} onTip={onTip} />
    case 'scatter':
      return <SampleScatter coordinates={data} onTip={onTip} onTipEnd={onTipEnd} />
    case 'spatial_map':
      return figure.id === 'gene_maps' ? (
        <GeneMap maps={data} onTip={onTip} />
      ) : (
        <DomainMap assignments={data} onTip={onTip} />
      )
    case 'network':
      return <Network rows={data} onTip={onTip} onTipEnd={onTipEnd} />
    case 'grouped_table':
      return <GroupedTable groups={data} />
    default:
      return <DataTable rows={Array.isArray(data) ? data : []} />
  }
}

/* ------------------------------------------------------------ stat tiles -- */
const TILES: [string, string][] = [
  ['n_cells_input', 'Cells in'],
  ['n_cells_kept', 'Cells kept'],
  ['n_doublets_flagged', 'Doublets flagged'],
  ['median_genes_per_cell', 'Median genes per cell'],
  ['median_mito_pct', 'Median mitochondrial %'],
  ['n_spots_input', 'Spots in'],
  ['n_spots_kept', 'Spots kept'],
  ['median_counts_per_spot', 'Median counts per spot'],
  ['median_genes_per_spot', 'Median genes per spot'],
  ['min_library_size', 'Smallest library'],
  ['max_library_size', 'Largest library'],
  ['depth_ratio', 'Depth ratio, largest to smallest'],
  ['min_detected_genes', 'Fewest genes detected'],
  ['max_detected_genes', 'Most genes detected'],
  ['n_profiles', 'Pseudobulk profiles'],
  ['n_profiles_dropped', 'Profiles below the cell minimum'],
  ['n_cell_types_tested', 'Cell types tested'],
  ['n_significant', 'Genes past the threshold'],
]

function SummaryTiles({ data }: { data: Record<string, any> }) {
  const tiles = TILES.filter(([key]) => typeof data?.[key] === 'number')
  const input = data?.n_cells_input ?? data?.n_spots_input
  const kept = data?.n_cells_kept ?? data?.n_spots_kept
  return (
    <div className="stat-row">
      {tiles.map(([key, label]) => (
        <div className="stat" key={key}>
          <div className="stat-label">{label}</div>
          <div className="stat-value">{fmt(data[key])}</div>
        </div>
      ))}
      {Array.isArray(data?.untestable_cell_types) && data.untestable_cell_types.length ? (
        <p className="hint stat-wide">
          Not tested, because at least one condition had fewer than two samples with enough
          cells of this type: {data.untestable_cell_types.join(', ')}.
        </p>
      ) : null}
      {typeof input === 'number' && typeof kept === 'number' && input > 0 ? (
        <div className="stat">
          <div className="stat-label">Removed by quality control</div>
          <div className="stat-value">{fmt(input - kept)}</div>
          <div className="stat-note">{((1 - kept / input) * 100).toFixed(1)}% of the input</div>
        </div>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------- bars -- */
function BarChart({
  values, labels, valueName, categoryName, onTip, onTipEnd,
}: {
  values: number[]; labels: string[]; valueName: string; categoryName: string
  onTip: TipFn; onTipEnd: () => void
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const height = 240
  const pad = { l: 52, r: 12, t: 12, b: 34 }
  const plotW = Math.max(0, width - pad.l - pad.r)
  const plotH = height - pad.t - pad.b
  const ticks = niceTicks(Math.max(...values, 0))
  const top = ticks[ticks.length - 1] || 1
  const band = values.length ? plotW / values.length : 0
  const barW = Math.max(2, Math.min(24, band - 2))
  //: Label every category only while the labels still fit.
  const labelEvery = Math.max(1, Math.ceil(22 / Math.max(band, 1)))
  return (
    <div ref={ref}>
      {width > 0 ? (
        <svg width={width} height={height} role="img" aria-label={`${categoryName} ${valueName}`}>
          {ticks.map((t) => {
            const y = pad.t + plotH - (t / top) * plotH
            return (
              <g key={t}>
                <line className="viz-grid" x1={pad.l} x2={width - pad.r} y1={y} y2={y} />
                <text className="viz-tick" x={pad.l - 8} y={y} dy="0.32em" textAnchor="end">{fmt(t)}</text>
              </g>
            )
          })}
          {values.map((v, i) => {
            const h = (v / top) * plotH
            const x = pad.l + i * band + (band - barW) / 2
            return (
              <g key={i}>
                <path
                  className="viz-mark"
                  d={barPath(x, pad.t + plotH - h, barW, Math.max(h, 0.5))}
                  fill={SERIES[0]}
                />
                {/* The hit target is the whole band, not the painted bar. */}
                <rect
                  x={pad.l + i * band} y={pad.t} width={band} height={plotH} fill="transparent"
                  onMouseMove={(e) => onTip(e, <><strong>{fmt(v)}</strong> {valueName}<div className="viz-tip-sub">{categoryName} {labels[i]}</div></>)}
                  onMouseLeave={onTipEnd}
                />
                {i % labelEvery === 0 ? (
                  <text className="viz-tick" x={pad.l + i * band + band / 2} y={height - pad.b + 16} textAnchor="middle">
                    {labels[i]}
                  </text>
                ) : null}
              </g>
            )
          })}
          <line className="viz-axis" x1={pad.l} x2={width - pad.r} y1={pad.t + plotH} y2={pad.t + plotH} />
        </svg>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------ scree -- */
function ScreeChart({ values, onTip, onTipEnd }: { values: number[]; onTip: TipFn; onTipEnd: () => void }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const height = 240
  const pad = { l: 52, r: 16, t: 12, b: 34 }
  const plotW = Math.max(0, width - pad.l - pad.r)
  const plotH = height - pad.t - pad.b
  const pct = values.map((v) => v * 100)
  const ticks = niceTicks(Math.max(...pct, 0))
  const top = ticks[ticks.length - 1] || 1
  const x = (i: number) => pad.l + (pct.length > 1 ? (i / (pct.length - 1)) * plotW : plotW / 2)
  const y = (v: number) => pad.t + plotH - (v / top) * plotH
  const path = pct.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join('')
  const last = pct.length - 1
  return (
    <div ref={ref}>
      {width > 0 ? (
        <svg
          width={width} height={height} role="img" aria-label="Variance explained per component"
          onMouseMove={(e) => {
            const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
            const i = Math.round(((e.clientX - box.left - pad.l) / Math.max(plotW, 1)) * last)
            const idx = Math.max(0, Math.min(last, i))
            setHover(idx)
            onTip(e, <><strong>{pct[idx].toFixed(2)}%</strong> of variance<div className="viz-tip-sub">Component {idx + 1}</div></>)
          }}
          onMouseLeave={() => { setHover(null); onTipEnd() }}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line className="viz-grid" x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} />
              <text className="viz-tick" x={pad.l - 8} y={y(t)} dy="0.32em" textAnchor="end">{fmt(t)}%</text>
            </g>
          ))}
          {pct.map((_, i) =>
            i % Math.max(1, Math.ceil(pct.length / 12)) === 0 || i === last ? (
              <text key={i} className="viz-tick" x={x(i)} y={height - pad.b + 16} textAnchor="middle">{i + 1}</text>
            ) : null,
          )}
          <line className="viz-axis" x1={pad.l} x2={width - pad.r} y1={pad.t + plotH} y2={pad.t + plotH} />
          {hover !== null ? <line className="viz-crosshair" x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + plotH} /> : null}
          <path d={path} fill="none" stroke={SERIES[0]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={x(last)} cy={y(pct[last])} r={4} fill={SERIES[0]} className="viz-ring" />
          {hover !== null ? <circle cx={x(hover)} cy={y(pct[hover])} r={4} fill={SERIES[0]} className="viz-ring" /> : null}
        </svg>
      ) : null}
    </div>
  )
}

/* -------------------------------------------------------------- embedding -- */
function useScale(xs: number[], ys: number[], width: number, height: number, pad: number, equal = false) {
  return useMemo(() => {
    const xmin = Math.min(...xs), xmax = Math.max(...xs)
    const ymin = Math.min(...ys), ymax = Math.max(...ys)
    const sx = (width - 2 * pad) / Math.max(xmax - xmin, 1e-9)
    const sy = (height - 2 * pad) / Math.max(ymax - ymin, 1e-9)
    const s = equal ? Math.min(sx, sy) : 0
    const kx = equal ? s : sx
    const ky = equal ? s : sy
    const ox = pad + ((width - 2 * pad) - (xmax - xmin) * kx) / 2
    const oy = pad + ((height - 2 * pad) - (ymax - ymin) * ky) / 2
    return {
      px: (v: number) => ox + (v - xmin) * kx,
      //: Mathematical y grows upward; tissue (image) y grows downward.
      py: (v: number, flip = true) => (flip ? oy + (ymax - v) * ky : oy + (v - ymin) * ky),
    }
  }, [xs, ys, width, height, pad, equal])
}

function nearest(points: [number, number][], mx: number, my: number, within = 24): number {
  let best = -1
  let bestD = within * within
  for (let i = 0; i < points.length; i++) {
    const dx = points[i][0] - mx, dy = points[i][1] - my
    const d = dx * dx + dy * dy
    if (d < bestD) { bestD = d; best = i }
  }
  return best
}

function GroupChips({
  groups, counts, noun, selected, onSelect,
}: { groups: number[]; counts: Map<number, number>; noun: string; selected: number | null; onSelect: (g: number | null) => void }) {
  return (
    <div className="viz-chips" role="group" aria-label={`Highlight a ${noun}`}>
      <button type="button" aria-pressed={selected === null} onClick={() => onSelect(null)}>All</button>
      {groups.map((g) => (
        <button key={g} type="button" aria-pressed={selected === g} onClick={() => onSelect(selected === g ? null : g)}>
          {noun} {g} <span className="muted">{counts.get(g)}</span>
        </button>
      ))}
    </div>
  )
}

function Embedding({ x, y, membership, onTip }: { x: number[]; y: number[]; membership?: number[]; onTip: TipFn }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [selected, setSelected] = useState<number | null>(null)
  const height = Math.min(460, Math.max(300, width * 0.62))
  const { px, py } = useScale(x, y, width, height, 18)
  const points = useMemo<[number, number][]>(() => x.map((v, i) => [px(v), py(y[i])]), [x, y, px, py])
  const groups = useMemo(() => (membership ? [...new Set(membership)].sort((a, b) => a - b) : []), [membership])
  const counts = useMemo(() => {
    const c = new Map<number, number>()
    membership?.forEach((g) => c.set(g, (c.get(g) ?? 0) + 1))
    return c
  }, [membership])
  const centroids = useMemo(() => groups.map((g) => {
    let sx = 0, sy = 0, n = 0
    points.forEach(([a, b], i) => { if (membership![i] === g) { sx += a; sy += b; n++ } })
    return { g, cx: sx / n, cy: sy / n }
  }), [groups, points, membership])
  return (
    <div ref={ref}>
      {membership ? <GroupChips groups={groups} counts={counts} noun="Cluster" selected={selected} onSelect={setSelected} /> : null}
      {width > 0 ? (
        <svg
          width={width} height={height} role="img" aria-label="UMAP layout of cells"
          onMouseMove={(e) => {
            const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
            const i = nearest(points, e.clientX - box.left, e.clientY - box.top)
            if (i >= 0) onTip(e, membership ? <><strong>Cluster {membership[i]}</strong><div className="viz-tip-sub">{counts.get(membership[i])} cells drawn in this cluster</div></> : <strong>Cell {i + 1}</strong>)
          }}
        >
          {/* No selection: one series, in slot 1. A selection: the emphasis
              pattern, the chosen cluster in slot 1 drawn over every other cell
              in grey. */}
          {[false, true].map((pass) =>
            points.map(([a, b], i) => {
              const chosen = selected === null || membership?.[i] === selected
              if (chosen !== pass) return null
              return (
                <circle key={`${pass ? 'c' : 'o'}${i}`} cx={a} cy={b}
                  r={chosen && selected !== null ? 2.6 : 2}
                  fill={chosen ? SERIES[0] : 'var(--viz-neutral)'}
                  opacity={chosen ? 0.8 : 0.45} />
              )
            }),
          )}
          {centroids.map(({ g, cx, cy }) => (
            <text key={g} className="viz-centroid" x={cx} y={cy} textAnchor="middle" dy="0.35em">{g}</text>
          ))}
        </svg>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------ stacked bar -- */
function StackedBar({ proportions, onTip, onTipEnd }: { proportions: Record<string, Record<string, number>>; onTip: TipFn; onTipEnd: () => void }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const samples = Object.keys(proportions)
  const types = useMemo(() => [...new Set(samples.flatMap((s) => Object.keys(proportions[s])))].sort(), [proportions, samples])
  //: Eight categorical slots is the ceiling; any further populations fold into
  //: "Other" in neutral grey rather than a generated ninth hue.
  const shown = types.length > 8 ? types.slice(0, 7) : types
  const folded = types.length > 8 ? types.slice(7) : []
  const series = [...shown, ...(folded.length ? ['Other'] : [])]
  const colorOf = (name: string) => (name === 'Other' ? 'var(--viz-neutral)' : SERIES[shown.indexOf(name)])
  const valueOf = (sample: string, name: string) =>
    name === 'Other' ? folded.reduce((a, t) => a + (proportions[sample][t] ?? 0), 0) : proportions[sample][name] ?? 0
  const height = 260
  const pad = { l: 44, r: 12, t: 12, b: 34 }
  const plotW = Math.max(0, width - pad.l - pad.r)
  const plotH = height - pad.t - pad.b
  const band = samples.length ? plotW / samples.length : 0
  const barW = Math.max(6, Math.min(24, band - 8))
  return (
    <div ref={ref}>
      <ul className="viz-legend">
        {series.map((name) => (
          <li key={name}><span className="swatch" style={{ background: colorOf(name) }} />{name}</li>
        ))}
      </ul>
      {width > 0 ? (
        <svg width={width} height={height} role="img" aria-label="Composition by sample">
          {[0, 25, 50, 75, 100].map((t) => {
            const yy = pad.t + plotH - (t / 100) * plotH
            return (
              <g key={t}>
                <line className="viz-grid" x1={pad.l} x2={width - pad.r} y1={yy} y2={yy} />
                <text className="viz-tick" x={pad.l - 8} y={yy} dy="0.32em" textAnchor="end">{t}%</text>
              </g>
            )
          })}
          {samples.map((sample, si) => {
            let acc = 0
            const x = pad.l + si * band + (band - barW) / 2
            return (
              <g key={sample}>
                {series.map((name) => {
                  const v = valueOf(sample, name)
                  const h = (v / 100) * plotH
                  const yy = pad.t + plotH - ((acc + v) / 100) * plotH
                  acc += v
                  //: The 2px gap between segments is surface, not a stroke.
                  return h > 0 ? (
                    <rect key={name} x={x} y={yy} width={barW} height={Math.max(h - 2, 0.5)} fill={colorOf(name)}
                      onMouseMove={(e) => onTip(e, <><strong>{v.toFixed(1)}%</strong><div className="viz-tip-sub">{name} · {sample}</div></>)}
                      onMouseLeave={onTipEnd} />
                  ) : null
                })}
                <text className="viz-tick" x={pad.l + si * band + band / 2} y={height - pad.b + 16} textAnchor="middle">{sample}</text>
              </g>
            )
          })}
        </svg>
      ) : null}
    </div>
  )
}

/* ---------------------------------------------------------------- volcano -- */
function Volcano({ rows, fdr, onTip }: { rows: any[]; fdr: number; onTip: TipFn }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const height = 320
  const pad = { l: 52, r: 16, t: 16, b: 40 }
  const pts = useMemo(() => rows
    .filter((r) => Number.isFinite(r.log2FoldChange) && Number.isFinite(r.padj) && r.padj > 0)
    .map((r) => ({ ...r, nlp: -Math.log10(r.padj) })), [rows])
  const xmax = Math.max(1, ...pts.map((p) => Math.abs(p.log2FoldChange)))
  const ymax = niceTicks(Math.max(1, ...pts.map((p) => p.nlp))).slice(-1)[0]
  const plotW = Math.max(0, width - pad.l - pad.r)
  const plotH = height - pad.t - pad.b
  const px = (v: number) => pad.l + ((v + xmax) / (2 * xmax)) * plotW
  const py = (v: number) => pad.t + plotH - (v / ymax) * plotH
  const cls = (p: any) => (p.padj < fdr ? (p.log2FoldChange > 0 ? 'up' : 'down') : 'ns')
  const screen = pts.map((p) => [px(p.log2FoldChange), py(p.nlp)] as [number, number])
  const labelled = [...pts].filter((p) => p.padj < fdr).sort((a, b) => a.padj - b.padj).slice(0, 5)
  const up = pts.filter((p) => cls(p) === 'up').length
  const down = pts.filter((p) => cls(p) === 'down').length
  return (
    <div ref={ref}>
      <ul className="viz-legend">
        <li><span className="swatch dot" style={{ background: 'var(--viz-up)' }} />Up, significant <span className="muted">{up}</span></li>
        <li><span className="swatch dot" style={{ background: 'var(--viz-down)' }} />Down, significant <span className="muted">{down}</span></li>
        <li><span className="swatch dot" style={{ background: 'var(--viz-neutral)' }} />Not significant <span className="muted">{pts.length - up - down}</span></li>
      </ul>
      {width > 0 ? (
        <svg width={width} height={height} role="img" aria-label="Volcano plot"
          onMouseMove={(e) => {
            const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
            const i = nearest(screen, e.clientX - box.left, e.clientY - box.top)
            if (i >= 0) { const p = pts[i]; onTip(e, <><strong>{p.gene}</strong><div className="viz-tip-sub">log2 fold change {fmt(p.log2FoldChange)} · adjusted p {fmt(p.padj)}</div></>) }
          }}>
          <line className="viz-axis" x1={pad.l} x2={width - pad.r} y1={pad.t + plotH} y2={pad.t + plotH} />
          <line className="viz-grid" x1={px(0)} x2={px(0)} y1={pad.t} y2={pad.t + plotH} />
          {/* The threshold this run used, from its recorded parameters. */}
          <line className="viz-threshold" x1={pad.l} x2={width - pad.r} y1={py(-Math.log10(fdr))} y2={py(-Math.log10(fdr))} />
          <text className="viz-tick" x={width - pad.r} y={py(-Math.log10(fdr)) - 6} textAnchor="end">FDR {fdr}</text>
          {pts.map((p, i) => (
            <circle key={i} cx={screen[i][0]} cy={screen[i][1]} r={cls(p) === 'ns' ? 2 : 3}
              fill={cls(p) === 'up' ? 'var(--viz-up)' : cls(p) === 'down' ? 'var(--viz-down)' : 'var(--viz-neutral)'} />
          ))}
          {labelled.map((p) => (
            <text key={p.gene} className="viz-label" x={px(p.log2FoldChange)} y={py(p.nlp) - 7} textAnchor="middle">{p.gene}</text>
          ))}
          <text className="viz-tick" x={pad.l + plotW / 2} y={height - 8} textAnchor="middle">log2 fold change</text>
          <text className="viz-tick" x={14} y={pad.t + plotH / 2} textAnchor="middle" transform={`rotate(-90 14 ${pad.t + plotH / 2})`}>−log10 adjusted p</text>
        </svg>
      ) : null}
    </div>
  )
}

/* ---------------------------------------------------------- sample scatter -- */
function SampleScatter({ coordinates, onTip, onTipEnd }: { coordinates: number[][]; onTip: TipFn; onTipEnd: () => void }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const height = 280
  const xs = useMemo(() => coordinates.map((c) => c[0]), [coordinates])
  const ys = useMemo(() => coordinates.map((c) => c[1] ?? 0), [coordinates])
  const { px, py } = useScale(xs, ys, width, height, 28)
  return (
    <div ref={ref}>
      {width > 0 ? (
        <svg width={width} height={height} role="img" aria-label="Samples in principal component space">
          {coordinates.map((c, i) => (
            <g key={i}>
              <circle cx={px(c[0])} cy={py(c[1] ?? 0)} r={5} fill={SERIES[0]} className="viz-ring"
                onMouseMove={(e) => onTip(e, <><strong>Sample {i + 1}</strong><div className="viz-tip-sub">PC1 {fmt(c[0])} · PC2 {fmt(c[1] ?? 0)}</div></>)}
                onMouseLeave={onTipEnd} />
              <text className="viz-label" x={px(c[0]) + 8} y={py(c[1] ?? 0)} dy="0.32em">S{i + 1}</text>
            </g>
          ))}
        </svg>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------ tissue maps -- */
function DomainMap({ assignments, onTip }: { assignments: { coordinates: number[][]; domain: number[] }; onTip: TipFn }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [selected, setSelected] = useState<number | null>(null)
  const coords = assignments.coordinates
  const domain = assignments.domain
  const xs = useMemo(() => coords.map((c) => c[0]), [coords])
  const ys = useMemo(() => coords.map((c) => c[1]), [coords])
  const groups = useMemo(() => [...new Set(domain)].sort((a, b) => a - b), [domain])
  const counts = useMemo(() => {
    const c = new Map<number, number>()
    domain.forEach((g) => c.set(g, (c.get(g) ?? 0) + 1))
    return c
  }, [domain])

  // The full map, for one highlighted domain.
  const height = Math.min(460, Math.max(280, width * 0.7))
  const { px, py } = useScale(xs, ys, width, height, 14, true)
  const points = useMemo<[number, number][]>(() => coords.map((c) => [px(c[0]), py(c[1], false)]), [coords, px, py])

  // Small multiples share one nominal size and scale with the grid through viewBox.
  const spanX = Math.max(...xs) - Math.min(...xs) || 1
  const spanY = Math.max(...ys) - Math.min(...ys) || 1
  const mini = { w: 200, h: Math.round(Math.min(260, Math.max(120, (200 * spanY) / spanX))) }
  const small = useScale(xs, ys, mini.w, mini.h, 6, true)
  const miniPoints = useMemo<[number, number][]>(
    () => coords.map((c) => [small.px(c[0]), small.py(c[1], false)]),
    [coords, small],
  )

  return (
    <div ref={ref}>
      <GroupChips groups={groups} counts={counts} noun="Domain" selected={selected} onSelect={setSelected} />
      {selected === null ? (
        //: Past three categories no set of hues stays distinguishable on a
        //: scatter, so each domain gets its own small map rather than a colour.
        <div className="viz-multiples">
          {groups.map((g) => (
            <button key={g} type="button" className="viz-multiple" onClick={() => setSelected(g)}
              aria-label={`Domain ${g}, ${counts.get(g)} spots: show it on the full map`}>
              <svg viewBox={`0 0 ${mini.w} ${mini.h}`} aria-hidden="true">
                {miniPoints.map(([a, b], i) => (domain[i] === g ? null : (
                  <circle key={i} cx={a} cy={b} r={1.6} fill="var(--viz-neutral)" opacity={0.35} />
                )))}
                {miniPoints.map(([a, b], i) => (domain[i] === g ? (
                  <circle key={`d${i}`} cx={a} cy={b} r={1.9} fill={SERIES[0]} />
                ) : null))}
              </svg>
              <span>
                Domain {g} <span className="muted">{counts.get(g)} spots</span>
              </span>
            </button>
          ))}
        </div>
      ) : width > 0 ? (
        <svg width={width} height={height} role="img" aria-label={`Domain ${selected} on the tissue section`}
          onMouseMove={(e) => {
            const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
            const i = nearest(points, e.clientX - box.left, e.clientY - box.top)
            if (i >= 0) onTip(e, <><strong>Domain {domain[i]}</strong><div className="viz-tip-sub">spot at {fmt(coords[i][0], 0)}, {fmt(coords[i][1], 0)}</div></>)
          }}>
          {points.map(([a, b], i) => (domain[i] === selected ? null : (
            <circle key={i} cx={a} cy={b} r={3} fill="var(--viz-neutral)" opacity={0.35} />
          )))}
          {points.map(([a, b], i) => (domain[i] === selected ? (
            <circle key={`s${i}`} cx={a} cy={b} r={3.2} fill={SERIES[0]} />
          ) : null))}
        </svg>
      ) : null}
    </div>
  )
}

function GeneMap({ maps, onTip }: { maps: { coordinates: number[][]; genes: Record<string, number[]> }; onTip: TipFn }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const names = Object.keys(maps.genes ?? {})
  const [gene, setGene] = useState(names[0] ?? '')
  const values = maps.genes?.[gene] ?? []
  const coords = maps.coordinates
  const height = Math.min(460, Math.max(280, width * 0.7))
  const xs = useMemo(() => coords.map((c) => c[0]), [coords])
  const ys = useMemo(() => coords.map((c) => c[1]), [coords])
  const { px, py } = useScale(xs, ys, width, height, 14, true)
  const points = useMemo<[number, number][]>(() => coords.map((c) => [px(c[0]), py(c[1], false)]), [coords, px, py])
  const vmax = Math.max(...values, 1e-9)
  return (
    <div ref={ref}>
      <div className="viz-chips" role="group" aria-label="Gene">
        {names.map((name) => (
          <button key={name} type="button" aria-pressed={gene === name} onClick={() => setGene(name)}>{name}</button>
        ))}
      </div>
      <div className="viz-scale">
        <span className="muted small">0</span>
        <span className="viz-scale-bar" aria-hidden="true" />
        <span className="muted small">{fmt(vmax)} normalised</span>
      </div>
      {width > 0 ? (
        <svg width={width} height={height} role="img" aria-label={`Expression of ${gene} across the section`}
          onMouseMove={(e) => {
            const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
            const i = nearest(points, e.clientX - box.left, e.clientY - box.top)
            if (i >= 0) onTip(e, <><strong>{fmt(values[i])}</strong> normalised<div className="viz-tip-sub">{gene}</div></>)
          }}>
          {points.map(([a, b], i) => (
            //: One hue; strength carries magnitude and low values recede.
            <circle key={i} cx={a} cy={b} r={3} fill={SERIES[0]} opacity={0.08 + 0.92 * (values[i] / vmax)} />
          ))}
        </svg>
      ) : null}
    </div>
  )
}

/* ---------------------------------------------------------------- network -- */
function Network({ rows, onTip, onTipEnd }: { rows: any[]; onTip: TipFn; onTipEnd: () => void }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const significant = rows.filter((r) => r.significant && r.source !== r.target)
  const nodes = useMemo(() => [...new Set(significant.flatMap((r) => [r.source, r.target]))].sort(), [significant])
  const height = Math.min(420, Math.max(300, width * 0.6))
  if (!significant.length) {
    //: The measured wrapper stays mounted so the width is known if data arrives.
    return (
      <div ref={ref}>
        <p className="hint">No candidate interaction passed the threshold, so there is no network to draw. The table view lists every pair that was tested.</p>
      </div>
    )
  }
  const cx = width / 2, cy = height / 2
  const radius = Math.max(40, Math.min(width, height) / 2 - 70)
  const pos = new Map(nodes.map((n, i) => {
    const a = (i / nodes.length) * Math.PI * 2 - Math.PI / 2
    return [n, [cx + radius * Math.cos(a), cy + radius * Math.sin(a)] as [number, number]]
  }))
  const smax = Math.max(...significant.map((r) => r.score), 1e-9)
  return (
    <div ref={ref}>
      {width > 0 ? (
        <svg width={width} height={height} role="img" aria-label="Candidate communication network">
          <defs>
            <marker id="viz-arrow" viewBox="0 0 10 10" refX="16" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0L10,5L0,10z" fill={SERIES[0]} />
            </marker>
          </defs>
          {significant.map((r, i) => {
            const [x1, y1] = pos.get(r.source)!
            const [x2, y2] = pos.get(r.target)!
            return (
              <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={SERIES[0]} strokeOpacity={0.55}
                strokeWidth={1 + 4 * (r.score / smax)} markerEnd="url(#viz-arrow)"
                onMouseMove={(e) => onTip(e, <><strong>{r.ligand} → {r.receptor}</strong><div className="viz-tip-sub">{r.source} → {r.target} · score {fmt(r.score)} · adjusted p {fmt(r.padj)}</div></>)}
                onMouseLeave={onTipEnd} />
            )
          })}
          {nodes.map((n) => {
            const [x, y] = pos.get(n)!
            const right = x >= cx
            return (
              <g key={n}>
                <circle cx={x} cy={y} r={7} className="viz-node" />
                <text className="viz-label" x={x + (right ? 12 : -12)} y={y} dy="0.32em" textAnchor={right ? 'start' : 'end'}>{n}</text>
              </g>
            )
          })}
        </svg>
      ) : null}
    </div>
  )
}

/* ----------------------------------------------------------------- tables -- */
function DataTable({ rows, limit = 50 }: { rows: any[]; limit?: number }) {
  if (!rows.length) return <p className="hint">Nothing to show.</p>
  const columns = Object.keys(rows[0]).filter((k) => typeof rows[0][k] !== 'object')
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, limit).map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className={typeof row[c] === 'number' ? 'num' : undefined}>
                  {typeof row[c] === 'number' ? fmt(row[c], 3) : String(row[c] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > limit ? <p className="hint">Showing {limit} of {rows.length} rows.</p> : null}
    </div>
  )
}

function GroupedTable({ groups }: { groups: Record<string, any[]> }) {
  const keys = Object.keys(groups ?? {})
  const [active, setActive] = useState(keys[0] ?? '')
  if (!keys.length) return <p className="hint">Nothing to show.</p>
  return (
    <>
      <div className="viz-chips" role="group" aria-label="Group">
        {keys.map((k) => (
          <button key={k} type="button" aria-pressed={active === k} onClick={() => setActive(k)}>
            {k} <span className="muted">{groups[k]?.length ?? 0}</span>
          </button>
        ))}
      </div>
      <DataTable rows={groups[active] ?? []} limit={25} />
    </>
  )
}

/** The table-view twin of every chart: the same values, no pointer needed. */
function FigureTable({ figure }: { figure: FigureSpec }) {
  const { kind, data, context = {} } = figure
  if (kind === 'bar') {
    return <DataTable rows={(data as number[]).map((v, i) => ({ [figure.id === 'cluster_sizes' ? 'cluster' : 'sample']: figure.id === 'cluster_sizes' ? i : `S${i + 1}`, value: v }))} />
  }
  if (kind === 'line') {
    return <DataTable rows={(data as number[]).map((v, i) => ({ component: i + 1, variance_pct: v * 100 }))} />
  }
  if (kind === 'embedding') {
    const counts = new Map<number, number>()
    ;(context.membership as number[] | undefined)?.forEach((g) => counts.set(g, (counts.get(g) ?? 0) + 1))
    return counts.size
      ? <DataTable rows={[...counts].sort((a, b) => a[0] - b[0]).map(([cluster, cells]) => ({ cluster, cells_drawn: cells }))} />
      : <p className="hint">{data.x.length} cells drawn. Cluster membership appears once the clustering step has run.</p>
  }
  if (kind === 'stacked_bar') {
    return <DataTable rows={Object.entries(data as Record<string, Record<string, number>>).map(([sample, row]) => ({ sample, ...row }))} />
  }
  if (kind === 'scatter') {
    return <DataTable rows={(data as number[][]).map((c, i) => ({ sample: `S${i + 1}`, pc1: c[0], pc2: c[1] ?? 0 }))} />
  }
  if (kind === 'spatial_map' && figure.id === 'domain_map') {
    const counts = new Map<number, number>()
    ;(data.domain as number[]).forEach((g) => counts.set(g, (counts.get(g) ?? 0) + 1))
    return <DataTable rows={[...counts].sort((a, b) => a[0] - b[0]).map(([domain, spots]) => ({ domain, spots_drawn: spots }))} />
  }
  if (kind === 'spatial_map') {
    return <DataTable rows={Object.entries(data.genes as Record<string, number[]>).map(([gene, vals]) => ({ gene, spots: vals.length, max: Math.max(...vals), mean: vals.reduce((a, b) => a + b, 0) / Math.max(vals.length, 1) }))} />
  }
  if (kind === 'grouped_table') return <GroupedTable groups={data} />
  return <DataTable rows={Array.isArray(data) ? data : []} />
}
