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

test('failureText: appends stderr when present', () => {
  const text = failureText({ ok: false, error: 'boom', exitCode: 1, stderrTail: 'trace' })
  assert.match(text, /boom/)
  assert.match(text, /trace/)
})
