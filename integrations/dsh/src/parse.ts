/** Pure parsing and rendering of graphlint `query --json` output. */

import type { JsonValue } from './types.js'

export type GraphSummaryLike = {
  graph_id: number
  entry: string
  warnings?: JsonValue[]
  is_dead_code?: boolean
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
  rootDir?: string
}

export type QueryOutcome = QueryFailure | QuerySuccess

const TAIL_LENGTH = 500

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
  const record = parsed as { result?: unknown; query_time_ms?: unknown; root_dir?: unknown }
  const result = record.result
  if (typeof result !== 'object' || result === null || !Array.isArray((result as { graphs?: unknown }).graphs)) {
    return {
      ok: false,
      error: `unexpected graphlint JSON shape (exit ${exitCode})`,
      exitCode,
      stdoutTail: stdout.slice(-TAIL_LENGTH),
    }
  }
  return {
    ok: true,
    exitCode,
    queryTimeMs: typeof record.query_time_ms === 'number' ? record.query_time_ms : undefined,
    result: result as QuerySuccess['result'],
    rootDir: typeof record.root_dir === 'string' ? record.root_dir : undefined,
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

/** Model-facing summary lines for a successful query. */
export function renderQueryText(outcome: QuerySuccess): string[] {
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
  return lines
}
