import assert from 'node:assert/strict'
import { join, resolve } from 'node:path'
import test from 'node:test'

import type { JsonValue, PluginContext } from '../src/types.js'
import { apply } from '../src/index.js'

/**
 * Integration coverage for the optional dsh-multi-folder compatibility: the
 * three tools are mounted against mock host services (the same style the
 * sibling dsh-python-env suite uses) and driven end to end, so the seam that
 * actually broke in the field — tool call → service probe → root guard →
 * spawned CLI cwd — is asserted, not just the pure guard helper.
 */

// Resolved through node:path so the expectations match the guard's own
// normalization on both Windows and POSIX.
const PRIMARY = resolve(process.cwd(), 'primary')
const SECONDARY = resolve(process.cwd(), '..', 'secondary')
const SECONDARY_SUB = join(SECONDARY, 'pkg')
const OUTSIDE = resolve(process.cwd(), '..', 'elsewhere')

type Captured = { argv: string[]; cwd: string }

interface Harness {
  tools: Map<string, { execute(args: unknown, exec: unknown): Promise<Record<string, JsonValue>> }>
  spawned: Captured[]
}

/** Minimal mock of every service the plugin injects (no runtime needed). */
function mount(multiFolder: unknown): Harness {
  const tools = new Map<string, { execute(args: unknown, exec: unknown): Promise<Record<string, JsonValue>> }>()
  const spawned: Captured[] = []
  const payload = JSON.stringify({
    result: { graphs: [], total_graphs: 0 },
    root_dir: null,
  })
  const reader = (text: string) => ({ readFrom: () => ({ text, nextOffset: text.length, lossy: false }) })
  const ctx = {
    tools: {
      register(definition: { name: string }) {
        tools.set(definition.name, definition as never)
        return () => {}
      },
    },
    subprocess: {
      async resolveExecutable(command: string) {
        return command === 'graphlint' ? 'graphlint.exe' : undefined
      },
      spawn(spec: Captured) {
        spawned.push({ argv: [...spec.argv], cwd: spec.cwd })
        return {
          pid: 1,
          done: Promise.resolve({ exitCode: 0, signal: null }),
          collected: { stdout: reader(payload), stderr: reader('') },
          terminate: () => {},
        }
      },
    },
    // No project-local virtualenv is reported, so resolution keeps the PATH hit.
    fs: { resolve: async (path: string, opts?: { cwd?: string }) => ({ path, cwd: opts?.cwd }), stat: async () => undefined },
    skills: { register: () => () => {} },
    jobs: { start: () => 'job-1' },
    timer: { timeout: (cb: () => void) => { const id = setTimeout(cb, 1); return () => clearTimeout(id) } },
    get: (name: string) => (name === 'multiFolder' ? multiFolder : undefined),
  } as unknown as PluginContext
  apply(ctx)
  return { tools, spawned }
}

const serviceOf = (dirs: string[]) => ({ list: async () => ({ workspace: PRIMARY, dirs, changed: false }) })
const exec = { agent: { session: { header: { cwd: PRIMARY } } } }
const execute = async (h: Harness, name: string, args: unknown) => h.tools.get(name)!.execute(args, exec)

for (const name of ['graphlint_query', 'graphlint_build', 'graphlint_config']) {
  test(`${name}: a configured secondary working directory is a valid root`, async () => {
    const h = mount(serviceOf([SECONDARY]))
    const value = await execute(h, name, { root_dir: SECONDARY, action: 'show' })
    assert.ok(!value.error, `expected success, got ${JSON.stringify(value)}`)
    assert.equal(h.spawned.at(-1)?.cwd, SECONDARY, 'the CLI runs with the secondary directory as its cwd')
  })

  test(`${name}: a subdirectory of a secondary root is a valid root`, async () => {
    const h = mount(serviceOf([SECONDARY]))
    const value = await execute(h, name, { root_dir: SECONDARY_SUB, action: 'show' })
    assert.ok(!value.error, `expected success, got ${JSON.stringify(value)}`)
    assert.equal(h.spawned.at(-1)?.cwd, SECONDARY_SUB)
  })

  test(`${name}: the default root is still the session workspace`, async () => {
    const h = mount(serviceOf([SECONDARY]))
    const value = await execute(h, name, { action: 'show' })
    assert.ok(!value.error)
    assert.equal(h.spawned.at(-1)?.cwd, PRIMARY)
  })

  test(`${name}: without multi-folder the plugin behaves exactly as before`, async () => {
    const h = mount(undefined)
    const denied = await execute(h, name, { root_dir: SECONDARY, action: 'show' })
    assert.match(String(denied.error), /must stay inside the session working directory/)
    assert.ok(!String(denied.error).includes('secondary working directories'))
    const ok = await execute(h, name, { action: 'show' })
    assert.ok(!ok.error, 'the tool still works with multi-folder absent')
    assert.equal(h.spawned.at(-1)?.cwd, PRIMARY)
  })

  test(`${name}: an unconfigured outside root is refused and names both roots and the remedy`, async () => {
    const h = mount(serviceOf([SECONDARY]))
    const denied = await execute(h, name, { root_dir: OUTSIDE, action: 'show' })
    assert.ok(String(denied.error).includes(PRIMARY), 'the refusal names the session workspace')
    assert.ok(String(denied.error).includes(SECONDARY), 'the refusal lists the configured secondary directory')
    assert.match(String(denied.error), /\/multi-folder/, 'the refusal names the remedy')
  })
}

test('a failing multi-folder probe degrades to the pre-existing guard', async () => {
  const h = mount({
    list: async () => {
      throw new Error('config unreadable')
    },
  })
  const denied = await execute(h, 'graphlint_query', { root_dir: SECONDARY })
  assert.match(String(denied.error), /must stay inside the session working directory/)
  const ok = await execute(h, 'graphlint_query', {})
  assert.ok(!ok.error)
  assert.equal(h.spawned.at(-1)?.cwd, PRIMARY)
})

test('the probe never leaks into the CLI argv', async () => {
  const h = mount(serviceOf([SECONDARY]))
  await execute(h, 'graphlint_query', { root_dir: SECONDARY })
  const argv = h.spawned.at(-1)?.argv.join(' ') ?? ''
  assert.ok(!argv.includes('multiFolder'), 'argv carries only graphlint arguments')
})
