import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { SKILL_BODY } from '../src/skill-content.generated.js'

// Repository root relative to both lib/test/ and src/test/.
const skillUrl = new URL('../../../../graphlint/skill.md', import.meta.url)
const canonical = readFileSync(skillUrl, 'utf8')

function stripFrontmatter(text: string): string {
  if (!text.startsWith('---')) {
    throw new Error('graphlint/skill.md must start with YAML frontmatter')
  }
  const end = text.indexOf('\n---', 3)
  if (end === -1) throw new Error('graphlint/skill.md: unterminated YAML frontmatter')
  return text.slice(end + 4)
}

function frontmatterOf(text: string): string {
  return text.slice(4, text.indexOf('\n---', 3))
}

test('generated SKILL_BODY is byte-identical to graphlint/skill.md (frontmatter stripped)', () => {
  // Mirrors graphlint.agent_tools.skill_body() on the Python side.
  const expected = stripFrontmatter(canonical).trim() + '\n'
  assert.equal(SKILL_BODY, expected)
})

test('canonical frontmatter declares the skill name and description', () => {
  const fm = frontmatterOf(canonical)
  assert.match(fm, /^name: graphlint$/m)
  assert.match(fm, /^description: .+$/m)
})

test('canonical body covers the core CLI surface', () => {
  const body = stripFrontmatter(canonical)
  for (const needle of [
    'graphlint query',
    'graphlint build --force',
    '--warn-types',
    '--reachability',
    '--public-as-entry',
    '--fail-on',
    'add-entry-rule',
    'getattr',
    'importlib',
    '~200 s',
  ]) {
    assert.ok(body.includes(needle), `canonical body must mention: ${needle}`)
  }
})
