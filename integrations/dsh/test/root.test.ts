import assert from 'node:assert/strict'
import { join, resolve } from 'node:path'
import test from 'node:test'

import { guardAllowedRoot, guardRoot, isWithin, sessionCwd } from '../src/root.js'

const base = resolve(process.cwd(), 'proj')
const sec = resolve(base, '..', 'sec')
const secTwo = resolve(base, '..', 'sec-two')

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

test('guardRoot: a relative path resolves against the session root, not the host cwd', () => {
  assert.equal(guardRoot('src', base), join(base, 'src'))
  assert.equal(guardRoot('.', base), base)
})

test('guardRoot: refuses a directory outside the session root', () => {
  assert.throws(() => guardRoot(resolve(base, '..'), base), /must stay inside the session working directory/)
})

test('guardRoot: refuses a sibling directory', () => {
  assert.throws(() => guardRoot(resolve(base, '..', 'other'), base), /RootOutsideSessionError|must stay inside/)
})

test('guardAllowedRoot: extra roots extend the allowed set', () => {
  assert.equal(guardAllowedRoot(sec, base, [sec]), sec)
  assert.equal(guardAllowedRoot(join(sec, 'pkg'), base, [sec]), join(sec, 'pkg'))
  assert.equal(guardAllowedRoot(join(base, 'src'), base, [sec]), join(base, 'src'), 'primary still wins')
  assert.equal(guardAllowedRoot('src', base, [sec]), join(base, 'src'), 'relative paths stay primary-relative')
  assert.equal(guardAllowedRoot(undefined, base, [sec]), base)
  assert.equal(guardAllowedRoot(secTwo, base, [sec, secTwo]), secTwo, 'any configured root is allowed')
})

test('guardAllowedRoot: no extra roots behaves exactly like guardRoot', () => {
  assert.equal(guardAllowedRoot(join(base, 'src'), base, []), guardRoot(join(base, 'src'), base))
  assert.throws(
    () => guardAllowedRoot(resolve(base, '..', 'other'), base, []),
    /must stay inside the session working directory/,
  )
})

test('guardAllowedRoot: refusal outside every root names the configured secondary directories', () => {
  const error = (() => {
    try {
      guardAllowedRoot(resolve(base, '..', 'elsewhere'), base, [sec])
    } catch (e) {
      return e as Error
    }
    return undefined
  })()
  assert.ok(error, 'an outside root must be refused')
  assert.match(error.message, /secondary working directories/)
  assert.ok(error.message.includes(sec), 'the refusal lists the configured secondary directories')
  assert.match(error.message, /\/multi-folder/, 'the refusal names the remedy')
})

test('guardAllowedRoot: without multi-folder the refusal keeps the original wording', () => {
  const error = (() => {
    try {
      guardAllowedRoot(resolve(base, '..', 'elsewhere'), base, [])
    } catch (e) {
      return e as Error
    }
    return undefined
  })()
  assert.ok(error, 'an outside root must be refused')
  assert.ok(!error.message.includes('secondary working directories'), 'no multi-folder wording when unconfigured')
  assert.match(error.message, /builds a huge index and can block for many minutes/)
})

test('sessionCwd: prefers the session header cwd', () => {
  const exec = { agent: { session: { header: { cwd: base } } } }
  assert.equal(sessionCwd(exec), base)
})

test('sessionCwd: falls back to process.cwd() without an agent chain', () => {
  assert.equal(sessionCwd(undefined), process.cwd())
})
