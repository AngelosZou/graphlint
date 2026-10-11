import assert from 'node:assert/strict'
import test from 'node:test'

import { failureText, parseQueryOutput, renderQueryText } from '../src/parse.js'

const VALID = JSON.stringify({
  status: 'ok',
  query_time_ms: 8,
  root_dir: 'D:\\proj',
  result: {
    graphs: [
      { graph_id: 1, entry: 'a.py (a)', warnings: ['dead_code'], is_dead_code: true },
      { graph_id: 2, entry: 'b.py (b)', warnings: [], is_dead_code: false },
    ],
    total_graphs: 2,
    has_more: false,
    warnings_summary: { dead_code: 1, unused_import: 3 },
  },
})

test('parseQueryOutput: parses a valid result', () => {
  const outcome = parseQueryOutput(VALID, '', 0)
  assert.ok(outcome.ok)
  assert.equal(outcome.queryTimeMs, 8)
  assert.equal(outcome.rootDir, 'D:\\proj')
  if (!('result' in outcome)) throw new Error('expected a list outcome')
  assert.equal(outcome.result.graphs.length, 2)
})

test('parseQueryOutput: rejects empty stdout', () => {
  const outcome = parseQueryOutput('', 'some error', 1)
  assert.ok(!outcome.ok)
  assert.match(outcome.error, /no output/)
})

test('parseQueryOutput: rejects malformed JSON with tails', () => {
  const outcome = parseQueryOutput('{not json', 'traceback', 1)
  assert.ok(!outcome.ok)
  assert.match(outcome.error, /could not parse/)
  assert.equal(outcome.stderrTail, 'traceback')
})

test('parseQueryOutput: rejects a JSON document without result.graphs', () => {
  const outcome = parseQueryOutput('{"status":"ok"}', '', 0)
  assert.ok(!outcome.ok)
  assert.match(outcome.error, /unexpected graphlint JSON shape/)
})

test('renderQueryText: summarizes totals, dead code and warnings', () => {
  const outcome = parseQueryOutput(VALID, '', 0)
  assert.ok(outcome.ok)
  const lines = renderQueryText(outcome)
  assert.ok(lines.some((line) => line.includes('2 component(s)')))
  assert.ok(lines.some((line) => line.includes('dead-code components: 1')))
  assert.ok(lines.some((line) => line.includes('dead_code:1')))
})

test('parseQueryOutput: keeps [graphlint] stderr notices on success', () => {
  const notice = '[graphlint] The default rule template has been updated (template v1 -> v2).'
  const outcome = parseQueryOutput(VALID, `unrelated noise\n${notice}\n`, 0)
  assert.ok(outcome.ok)
  assert.deepEqual(outcome.stderrNotes, [notice])
  assert.ok(renderQueryText(outcome).includes(notice))
})

test('parseQueryOutput: omits stderrNotes when stderr has no notices', () => {
  const outcome = parseQueryOutput(VALID, 'some warning from sqlite\n', 0)
  assert.ok(outcome.ok)
  assert.equal('stderrNotes' in outcome, false)
})

test('failureText: appends stderr when present', () => {
  const text = failureText({ ok: false, error: 'boom', exitCode: 1, stderrTail: 'trace' })
  assert.match(text, /boom/)
  assert.match(text, /trace/)
})

/** A real `query --graph-id 3 --json` payload (captured from the CLI). */
const DETAIL = JSON.stringify({
  status: 'ok',
  query_time_ms: 5,
  root_dir: 'D:\\proj',
  graph: {
    graph_id: 3,
    entry: '',
    files: ['pkg/orphan.py'],
    nodes: [
      {
        node_id: 3,
        name: 'orphan_a',
        qualified_name: 'pkg.orphan.orphan_a',
        node_type: 'function',
        file_path: 'pkg/orphan.py',
        line_start: 1,
        line_end: 2,
        is_deprecated: false,
        type_annotation: null,
        decorators: [],
      },
      {
        node_id: 4,
        name: 'orphan_b',
        qualified_name: 'pkg.orphan.orphan_b',
        node_type: 'function',
        file_path: 'pkg/orphan.py',
        line_start: 5,
        line_end: 6,
        is_deprecated: false,
        type_annotation: null,
        decorators: [],
      },
    ],
    edges: [
      {
        source_name: 'pkg.orphan.orphan_a',
        target_name: 'pkg.orphan.orphan_b',
        edge_type: 'call',
        file_path: 'pkg/orphan.py',
        line: 2,
      },
    ],
    warnings: [
      {
        warn_type: 'dead_code',
        severity: 'info',
        message: 'Component 3: unreachable — no CALL path from entry point',
        file_path: 'pkg/orphan.py',
        line: 1,
      },
    ],
  },
})

/** Parse a detail payload, failing loudly if it is not one. */
function detailOf(stdout: string, exitCode = 0) {
  const outcome = parseQueryOutput(stdout, '', exitCode)
  if (!outcome.ok || !('graph' in outcome)) {
    throw new Error(`expected a detail outcome, got ${JSON.stringify(outcome)}`)
  }
  return outcome
}

test('parseQueryOutput: parses the single-graph detail envelope (--graph-id)', () => {
  const outcome = detailOf(DETAIL)
  assert.equal(outcome.graph.graph_id, 3)
  assert.equal(outcome.graph.nodes?.length, 2)
  assert.equal(outcome.graph.edges?.length, 1)
  assert.equal(outcome.graph.warnings?.length, 1)
  assert.deepEqual(outcome.graph.files, ['pkg/orphan.py'])
  assert.equal(outcome.queryTimeMs, 5)
  assert.equal(outcome.rootDir, 'D:\\proj')
  // The detail envelope carries no `result.graphs` at all.
  assert.equal('result' in outcome, false)
})

test('renderQueryText: renders a detail outcome (entry, counts, nodes, edges, warnings)', () => {
  const text = renderQueryText(detailOf(DETAIL)).join('\n')
  assert.match(text, /graph #3 detail/)
  assert.match(text, /no entry point/)
  assert.match(text, /files: 1, nodes: 2, edges: 1, warnings: 1/)
  assert.match(text, /nodes \(2\):/)
  assert.match(text, /#3 orphan_a \(function\) pkg\/orphan\.py:1-2/)
  assert.match(text, /pkg\.orphan\.orphan_a -> pkg\.orphan\.orphan_b \(call\) pkg\/orphan\.py:2/)
  assert.match(text, /dead_code \[info\] pkg\/orphan\.py:1 — Component 3/)
  assert.match(text, /files \(1\):/)
})

test('renderQueryText: reports what the CLI cap omitted in detail mode', () => {
  const capped = JSON.stringify({
    status: 'ok',
    graph: { graph_id: 9, entry: 'a.py (main)', nodes: [], edges: [], warnings: [], nodes_omitted: 4, edges_omitted: 2, files_omitted: 1 },
  })
  const text = renderQueryText(detailOf(capped)).join('\n')
  assert.match(text, /4 node\(s\), 2 edge\(s\), 1 file\(s\) omitted/)
  assert.match(text, /entry: a\.py \(main\)/)
})

test('parseQueryOutput: keeps [graphlint] stderr notices on a detail run', () => {
  const notice = '[graphlint] The default rule template has been updated (template v1 -> v2).'
  const outcome = detailOfWithStderr(DETAIL, notice)
  assert.deepEqual(outcome.stderrNotes, [notice])
  assert.ok(renderQueryText(outcome).includes(notice))
})

function detailOfWithStderr(stdout: string, notice: string) {
  const outcome = parseQueryOutput(stdout, `noise\n${notice}\n`, 0)
  if (!outcome.ok || !('graph' in outcome)) throw new Error('expected a detail outcome')
  return outcome
}

test('parseQueryOutput: rejects a graph object without a numeric graph_id', () => {
  const outcome = parseQueryOutput('{"status":"ok","graph":{"entry":"x"}}', '', 0)
  assert.ok(!outcome.ok)
  assert.match(outcome.error, /unexpected graphlint JSON shape/)
})

test('parseQueryOutput: surfaces the CLI error envelope instead of an unknown shape', () => {
  const outcome = parseQueryOutput('{"status":"error","message":"Graph #999 not found. Range: 1-3","query_time_ms":2}', '', 0)
  assert.ok(!outcome.ok)
  assert.equal(outcome.error, 'Graph #999 not found. Range: 1-3')
  assert.equal(failureText(outcome), '[graphlint] error: Graph #999 not found. Range: 1-3')
})
