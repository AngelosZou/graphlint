/** Pure parsing and rendering of graphlint `query --json` output. */

import type { JsonValue } from './types.js'

export type GraphSummaryLike = {
  graph_id: number
  entry: string
  warnings?: JsonValue[]
  is_dead_code?: boolean
}

/** One node of a single-graph detail payload (`query --graph-id <id> --json`). */
export type GraphDetailNode = {
  node_id?: number
  name?: string
  qualified_name?: string
  node_type?: string
  file_path?: string
  line_start?: number
  line_end?: number
  is_deprecated?: boolean
  type_annotation?: string | null
  decorators?: JsonValue[]
}

/** One edge of a single-graph detail payload. */
export type GraphDetailEdge = {
  source_name?: string
  target_name?: string
  edge_type?: string
  file_path?: string
  line?: number
}

/** One warning of a single-graph detail payload. */
export type GraphDetailWarning = {
  warn_type?: string
  severity?: string
  message?: string
  file_path?: string
  line?: number
}

/**
 * The payload of `query --graph-id <id> --json`.
 *
 * Detail mode is a DIFFERENT envelope from the list query, not a variant of it:
 * the CLI (`graphlint/query/formatter.py::format_json_detail`) emits it under
 * the top-level `graph` key with no `result.graphs` at all. A parser that only
 * knows the list shape therefore rejects every detail query, however healthy
 * the CLI is. Nodes/edges/files are capped by the CLI (30/10/10) and the
 * `*_omitted` counters report how many entries that cap cut.
 */
export type GraphDetail = {
  graph_id: number
  entry?: string
  files?: string[]
  nodes?: GraphDetailNode[]
  edges?: GraphDetailEdge[]
  warnings?: GraphDetailWarning[]
  edges_omitted?: number
  nodes_omitted?: number
  files_omitted?: number
}

export type QueryFailure = {
  ok: false
  error: string
  exitCode: number | null
  stdoutTail?: string
  stderrTail?: string
}

export type QuerySuccess = {
  ok: true
  exitCode: number | null
  queryTimeMs?: number
  result: {
    graphs: GraphSummaryLike[]
    total_graphs?: number
    has_more?: boolean
    warnings_summary?: Record<string, number>
  }
  /** `[graphlint]`-prefixed notice lines the CLI wrote to stderr even on success
   *  (e.g. the one-time default-rule-template update notice). */
  stderrNotes?: string[]
  rootDir?: string
}

/** A successful `query --graph-id <id>` run — the single-graph envelope. */
export type QueryDetailSuccess = {
  ok: true
  exitCode: number | null
  queryTimeMs?: number
  graph: GraphDetail
  stderrNotes?: string[]
  rootDir?: string
}

export type QueryOutcome = QueryFailure | QuerySuccess | QueryDetailSuccess

/** The two success shapes `renderQueryText` can render. */
export type QueryTextOutcome = QuerySuccess | QueryDetailSuccess

const TAIL_LENGTH = 500

/** Caps for the model-facing detail text — the CLI's own cap is 30/10/10. */
const DETAIL_LIMITS = { warnings: 10, nodes: 15, edges: 10, files: 5 }

/** `[graphlint]`-prefixed notice lines from stderr, even when the query succeeded. */
function stderrNotices(stderr: string): string[] {
  return stderr
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.startsWith('[graphlint]'))
}

/** True when a success outcome carries a single-graph detail payload. */
export function isDetailOutcome(outcome: QueryTextOutcome): outcome is QueryDetailSuccess {
  return 'graph' in outcome
}

export function parseQueryOutput(stdout: string, stderr: string, exitCode: number | null): QueryOutcome {
  if (stdout.trim().length === 0) {
    return {
      ok: false,
      error: `graphlint produced no output (exit ${exitCode})`,
      exitCode,
      stderrTail: stderr.slice(-800),
    }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(stdout)
  } catch {
    return {
      ok: false,
      error: `could not parse graphlint JSON output (exit ${exitCode})`,
      exitCode,
      stdoutTail: stdout.slice(-TAIL_LENGTH),
      stderrTail: stderr.slice(-TAIL_LENGTH),
    }
  }
  const record = parsed as {
    result?: unknown
    graph?: unknown
    status?: unknown
    message?: unknown
    query_time_ms?: unknown
    root_dir?: unknown
  }
  // The CLI reports a semantic failure (e.g. `Graph #999 not found`) as an
  // error envelope on an exit-0 run, so this must be checked BEFORE the success
  // shapes: otherwise the real reason is swallowed as an unknown shape.
  if (record.status === 'error') {
    const message =
      typeof record.message === 'string' && record.message.trim().length > 0
        ? record.message
        : 'graphlint reported an error'
    return {
      ok: false,
      error: message,
      exitCode,
      ...(stderr.trim().length > 0 ? { stderrTail: stderr.slice(-TAIL_LENGTH) } : {}),
    }
  }
  const queryTimeMs = typeof record.query_time_ms === 'number' ? record.query_time_ms : undefined
  const rootDir = typeof record.root_dir === 'string' ? record.root_dir : undefined
  // Detail envelope (`--graph-id`): a single `graph` object, no `result.graphs`.
  const detail = record.graph
  if (
    typeof detail === 'object' &&
    detail !== null &&
    typeof (detail as { graph_id?: unknown }).graph_id === 'number'
  ) {
    const notices = stderrNotices(stderr)
    return {
      ok: true,
      exitCode,
      ...(queryTimeMs !== undefined ? { queryTimeMs } : {}),
      graph: detail as GraphDetail,
      ...(notices.length > 0 ? { stderrNotes: notices } : {}),
      ...(rootDir !== undefined ? { rootDir } : {}),
    }
  }
  // List envelope: `result.graphs`.
  const result = record.result
  if (typeof result !== 'object' || result === null || !Array.isArray((result as { graphs?: unknown }).graphs)) {
    return {
      ok: false,
      error: `unexpected graphlint JSON shape (exit ${exitCode})`,
      exitCode,
      stdoutTail: stdout.slice(-TAIL_LENGTH),
    }
  }
  const notices = stderrNotices(stderr)
  return {
    ok: true,
    exitCode,
    queryTimeMs,
    result: result as QuerySuccess['result'],
    ...(notices.length > 0 ? { stderrNotes: notices } : {}),
    rootDir,
  }
}

/** One-line description of a failure outcome, for render blocks. */
export function failureText(outcome: QueryFailure): string {
  const tail = outcome.stderrTail ?? outcome.stdoutTail
  return tail ? `[graphlint] error: ${outcome.error}\n${tail}` : `[graphlint] error: ${outcome.error}`
}

function hasWarnings(g: GraphSummaryLike): g is GraphSummaryLike & { warnings: JsonValue[] } {
  return Array.isArray(g.warnings) && g.warnings.length > 0
}

/** Model-facing summary lines for a successful query — list or detail mode. */
export function renderQueryText(outcome: QueryTextOutcome): string[] {
  return isDetailOutcome(outcome) ? renderGraphDetailText(outcome) : renderListText(outcome)
}

/** Model-facing summary lines for a list query. */
function renderListText(outcome: QuerySuccess): string[] {
  const r = outcome.result
  const lines: string[] = []
  const shown = r.graphs.length
  const total = r.total_graphs ?? shown
  lines.push(
    `[graphlint] query ok — ${total} component(s), ${shown} shown` +
      (r.has_more ? ' (more available)' : '') +
      (outcome.queryTimeMs !== undefined ? `, ${outcome.queryTimeMs}ms` : ''),
  )
  const dead = r.graphs.filter((g) => g.is_dead_code === true).length
  if (dead > 0) lines.push(`dead-code components: ${dead}`)
  const summary = r.warnings_summary
  if (summary && typeof summary === 'object') {
    const parts = Object.entries(summary).map(([key, value]) => `${key}:${value}`)
    if (parts.length > 0) lines.push(`warnings: ${parts.join(', ')}`)
  }
  const interesting = r.graphs.filter(hasWarnings).slice(0, 10)
  for (const g of interesting) {
    lines.push(`  #${g.graph_id} ${g.entry} [${g.warnings.length} warning(s)]`)
  }
  for (const note of outcome.stderrNotes ?? []) lines.push(note)
  return lines
}

/** ` pkg/mod.py:12-14` — the location suffix of a detail entry, when it has one. */
function location(filePath: string | undefined, line: number | undefined, end?: number | null): string {
  if (typeof filePath !== 'string' || filePath.length === 0) {
    return typeof line === 'number' ? `:${line}` : ''
  }
  if (typeof line !== 'number') return ` ${filePath}`
  return typeof end === 'number' && end !== line ? ` ${filePath}:${line}-${end}` : ` ${filePath}:${line}`
}

/** Model-facing lines for a single-graph detail query. */
function renderGraphDetailText(outcome: QueryDetailSuccess): string[] {
  const g = outcome.graph
  const files = g.files ?? []
  const nodes = g.nodes ?? []
  const edges = g.edges ?? []
  const warnings = g.warnings ?? []
  const lines: string[] = []
  const entry = typeof g.entry === 'string' && g.entry.length > 0 ? g.entry : '(no entry point — unreachable component)'
  lines.push(
    `[graphlint] graph #${g.graph_id} detail — entry: ${entry}` +
      (outcome.queryTimeMs !== undefined ? `, ${outcome.queryTimeMs}ms` : ''),
  )
  const omitted: string[] = []
  if ((g.nodes_omitted ?? 0) > 0) omitted.push(`${g.nodes_omitted} node(s)`)
  if ((g.edges_omitted ?? 0) > 0) omitted.push(`${g.edges_omitted} edge(s)`)
  if ((g.files_omitted ?? 0) > 0) omitted.push(`${g.files_omitted} file(s)`)
  lines.push(
    `files: ${files.length}, nodes: ${nodes.length}, edges: ${edges.length}, warnings: ${warnings.length}` +
      (omitted.length > 0 ? ` (+ ${omitted.join(', ')} omitted by the CLI's display cap)` : ''),
  )
  if (warnings.length > 0) {
    lines.push(`warnings (${warnings.length}):`)
    for (const w of warnings.slice(0, DETAIL_LIMITS.warnings)) {
      const kind = w.warn_type ?? 'warning'
      const severity = typeof w.severity === 'string' && w.severity.length > 0 ? ` [${w.severity}]` : ''
      const message = typeof w.message === 'string' && w.message.length > 0 ? ` — ${w.message}` : ''
      lines.push(`  ${kind}${severity}${location(w.file_path, w.line)}${message}`)
    }
    if (warnings.length > DETAIL_LIMITS.warnings) {
      lines.push(`  … ${warnings.length - DETAIL_LIMITS.warnings} more warning(s)`)
    }
  }
  if (nodes.length > 0) {
    lines.push(`nodes (${nodes.length}):`)
    for (const n of nodes.slice(0, DETAIL_LIMITS.nodes)) {
      const name = n.name ?? '(unnamed)'
      const type = typeof n.node_type === 'string' && n.node_type.length > 0 ? ` (${n.node_type})` : ''
      const deprecated = n.is_deprecated === true ? ' [deprecated]' : ''
      const id = typeof n.node_id === 'number' ? `#${n.node_id} ` : ''
      lines.push(`  ${id}${name}${type}${location(n.file_path, n.line_start, n.line_end)}${deprecated}`)
    }
    if (nodes.length > DETAIL_LIMITS.nodes) {
      lines.push(`  … ${nodes.length - DETAIL_LIMITS.nodes} more node(s)`)
    }
  }
  if (edges.length > 0) {
    lines.push(`edges (${edges.length}):`)
    for (const e of edges.slice(0, DETAIL_LIMITS.edges)) {
      const src = e.source_name ?? '?'
      const dst = e.target_name ?? '?'
      const type = typeof e.edge_type === 'string' && e.edge_type.length > 0 ? ` (${e.edge_type})` : ''
      lines.push(`  ${src} -> ${dst}${type}${location(e.file_path, e.line)}`)
    }
    if (edges.length > DETAIL_LIMITS.edges) {
      lines.push(`  … ${edges.length - DETAIL_LIMITS.edges} more edge(s)`)
    }
  }
  if (files.length > 0) {
    lines.push(`files (${files.length}):`)
    for (const f of files.slice(0, DETAIL_LIMITS.files)) lines.push(`  ${f}`)
    if (files.length > DETAIL_LIMITS.files) {
      lines.push(`  … ${files.length - DETAIL_LIMITS.files} more file(s)`)
    }
  }
  for (const note of outcome.stderrNotes ?? []) lines.push(note)
  return lines
}
