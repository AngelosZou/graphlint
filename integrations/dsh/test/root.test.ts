import assert from 'node:assert/strict'
import { join, resolve } from 'node:path'
import test from 'node:test'

import { guardRoot, isWithin, sessionCwd } from '../src/root.js'

const base = resolve(process.cwd(), 'proj')

test('isWithin: the base itself is inside', () => {
  assert.ok(isWithin(base, base))
})

test('isWithin: a subdirectory is inside', () => {
  assert.ok(isWithin(base, join(base, 'sub', 'deep')))
})

test('isWithin: a sibling directory is outside', () => {
  assert.ok(!isWithin(base, resolve(base, '..', 'sibling')))
})

test('isWithin: the parent directory is outside', () => {
  assert.ok(!isWithin(base, resolve(base, '..')))
})

test('guardRoot: defaults to the session working directory', () => {
  assert.equal(guardRoot(undefined, base), base)
})

test('guardRoot: resolves a subdirectory inside the session root', () => {
  assert.equal(guardRoot(join(base, 'src'), base), join(base, 'src'))
})

test('guardRoot: refuses a directory outside the session root', () => {
  assert.throws(() => guardRoot(resolve(base, '..'), base), /must stay inside the session working directory/)
})

test('guardRoot: refuses a sibling directory', () => {
  assert.throws(() => guardRoot(resolve(base, '..', 'other'), base), /RootOutsideSessionError|must stay inside/)
})

test('sessionCwd: prefers the session header cwd', () => {
  const exec = { agent: { session: { header: { cwd: base } } } }
  assert.equal(sessionCwd(exec), base)
})

test('sessionCwd: falls back to process.cwd() without an agent chain', () => {
  assert.equal(sessionCwd(undefined), process.cwd())
})
