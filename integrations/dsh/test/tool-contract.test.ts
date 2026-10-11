import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import test from 'node:test'

import type { JsonValue, PluginContext, ToolDefinition } from '../src/types.js'
import { apply } from '../src/index.js'
import { resolveSessionCwd } from '../src/root.js'

/**
 * Contract coverage for the DSH core surface this plugin is built against.
 *
 * The plugin used to restate the host service contracts by hand, which is why
 * `npm run build` could break (an undeclared `@deepseek-ai/dsh-tools`) and why a
 * real contract change (`JobSpec.owner` is a SessionId string, not the Agent
 * object) went unnoticed. These tests drive the mounted definitions through the
 * engine's OWN `defineTool` and assert the two seams that actually broke.
 */

const PRIMARY = resolve(process.cwd(), 'primary')

/**
 * The execution object the engine hands a tool. The published `Agent` face is
 * `{ id: SessionId }` plus runtime augmentations, so these stand-ins are cast
 * through `unknown` exactly the way the plugin's own structural types do.
 */
function execution(agent?: unknown, signal?: AbortSignal): import('../src/types.js').ToolRunContext {
  return { agent, signal } as unknown as import('../src/types.js').ToolRunContext
}


interface Mounted {
  definitions: Map<string, ToolDefinition>
  skills: { name: string }[]
  spawns: { argv: string[]; cwd: string }[]
  startedJobs: Record<string, unknown>[]
}

/** Mount the whole plugin against mock host services. */
function mount(options: {
  workingDirectory?: (agent: unknown, signal?: AbortSignal) => Promise<string>
  jobStart?: (spec: Record<string, unknown>) => string
} = {}): Mounted {
  const definitions = new Map<string, ToolDefinition>()
  const skills: { name: string }[] = []
  const spawns: { argv: string[]; cwd: string }[] = []
  const startedJobs: Record<string, unknown>[] = []
  const payload = JSON.stringify({ result: { graphs: [], total_graphs: 0 }, root_dir: null })
  const reader = (text: string) => ({ readFrom: () => ({ text, nextOffset: text.length, lossy: false }) })
  const ctx = {
    tools: {
      register(definition: ToolDefinition) {
        definitions.set(definition.name, definition)
        return () => {}
      },
    },
    subprocess: {
      async resolveExecutable(command: string) {
        return command === 'graphlint' ? 'graphlint.exe' : undefined
      },
      spawn(spec: { argv: readonly string[]; cwd: string }) {
        spawns.push({ argv: [...spec.argv], cwd: spec.cwd })
        return {
          done: Promise.resolve({ exitCode: 0, signal: null }),
          collected: { stdout: reader(payload), stderr: reader('') },
          terminate: () => {},
        }
      },
    },
    fs: { resolve: async (path: string) => ({ displayPath: path }), stat: async () => undefined },
    skills: { register: (skill: { name: string }) => { skills.push(skill); return () => {} } },
    jobs: { start: (spec: Record<string, unknown>) => (options.jobStart ?? (() => 'graphlint-build-1'))(spec) },
    timer: { timeout: (cb: () => void) => { const id = setTimeout(cb, 1); return () => clearTimeout(id) } },
    ...options.workingDirectory === undefined
      ? {}
      : { get: (name: string) => (name === 'workingDirectory' ? { ensure: options.workingDirectory } : undefined) },
  } as unknown as PluginContext
  apply(ctx)
  return { definitions, skills, spawns, startedJobs }
}

// ---------------------------------------------------------------------------
// The mounted tools are accepted by the engine's own defineTool
// ---------------------------------------------------------------------------

test('all three tools mount with output schemas the engine accepts', () => {
  const mounted = mount()
  assert.deepEqual(
    [...mounted.definitions.keys()].sort(),
    ['graphlint_build', 'graphlint_config', 'graphlint_query'],
  )
  for (const [name, definition] of mounted.definitions) {
    assert.equal(definition.name, name)
    assert.equal(typeof definition.description, 'string')
    assert.ok(definition.description.length > 0, `${name} needs a description`)
    // defineTool compiles the author parameter DSL into a raw object schema.
    const parameters = definition.parameters as { type?: string; properties?: Record<string, unknown> }
    assert.equal(parameters.type, 'object', `${name} parameters must compile to an object root`)
    assert.ok(parameters.properties && Object.keys(parameters.properties).length > 0)
    // The output declaration the registry requires.
    assert.equal(typeof definition.output.render, 'function')
    const schema = definition.output.schema as { type?: string }
    assert.equal(schema.type, 'object')
    assert.equal(typeof definition.execute, 'function')
    assert.ok((definition.timeoutMs ?? 0) > 0)
  }
})

test('the graphlint skill is mounted as a runtime skill', () => {
  const mounted = mount()
  assert.deepEqual(mounted.skills.map(skill => skill.name), ['graphlint'])
})

test('tool schemas keep the model-facing parameter names stable', () => {
  const mounted = mount()
  const propertiesOf = (name: string) => Object.keys(
    (mounted.definitions.get(name)!.parameters as { properties: Record<string, unknown> }).properties,
  ).sort()
  assert.deepEqual(propertiesOf('graphlint_query'), [
    'exclude_clean', 'graph_id', 'include_tests', 'public_as_entry', 'root_dir', 'warn_types',
  ])
  assert.deepEqual(propertiesOf('graphlint_build'), ['force', 'root_dir'])
  assert.deepEqual(propertiesOf('graphlint_config'), [
    'action', 'exclude_pattern', 'key', 'name', 'root_dir', 'rule_json', 'value',
  ])
})

// ---------------------------------------------------------------------------
// Session directory resolution (the workingDirectory seam)
// ---------------------------------------------------------------------------

test('resolveSessionCwd prefers the workingDirectory service', async () => {
  const seen: { agent: unknown; signal?: AbortSignal }[] = []
  const exec = execution({ id: 's-1', session: { header: { cwd: 'D:\\header' } } })
  const cwd = await resolveSessionCwd(exec, () => ({
    ensure: async (agent: unknown, signal?: AbortSignal) => {
      seen.push({ agent, signal })
      return PRIMARY
    },
  }))
  assert.equal(cwd, PRIMARY)
  assert.equal(seen.length, 1, 'ensure() is called once')
  assert.equal(seen[0]!.agent, exec.agent, 'ensure() receives the live runtime agent')
})

test('resolveSessionCwd falls back to the session header without the service', async () => {
  const exec = { agent: { id: 's-1', session: { header: { cwd: 'D:\\header' } } } }
  assert.equal(await resolveSessionCwd(exec, undefined), 'D:\\header')
  assert.equal(await resolveSessionCwd(exec, () => undefined), 'D:\\header')
})

test('resolveSessionCwd degrades to process.cwd() when the seam throws', async () => {
  const exec = { agent: { id: 's-1' } }
  const cwd = await resolveSessionCwd(exec, () => ({
    ensure: async () => {
      throw new Error('no live agent')
    },
  }))
  assert.equal(cwd, process.cwd())
})

test('a mounted tool uses the workingDirectory root by default', async () => {
  const mounted = mount({ workingDirectory: async () => PRIMARY })
  const exec = execution({ id: 's-1' })
  const value = await mounted.definitions.get('graphlint_query')!.execute({}, exec) as Record<string, JsonValue>
  assert.ok(!value.error, `expected success, got ${JSON.stringify(value)}`)
  assert.equal(mounted.spawns.at(-1)?.cwd, PRIMARY)
})

// ---------------------------------------------------------------------------
// The background-job owner is the SESSION ID, not the Agent object
// ---------------------------------------------------------------------------

test('graphlint_build hands the job registry the session id string', async () => {
  const mounted = mount()
  const exec = execution({ id: 'session-42', session: { header: { cwd: PRIMARY } } })
  const value = await mounted.definitions.get('graphlint_build')!.execute({}, exec) as Record<string, JsonValue>
  assert.ok(!value.error, `expected success, got ${JSON.stringify(value)}`)
  assert.equal(value.job_id, 'graphlint-build-1')
  assert.equal(mounted.definitions.size, 3)
})

test('graphlint_build passes owner as a string session id', async () => {
  let captured: Record<string, unknown> | undefined
  const mounted = mount({
    jobStart: (spec) => {
      captured = spec
      return 'job-9'
    },
  })
  const exec = execution({ id: 'session-42' })
  await mounted.definitions.get('graphlint_build')!.execute({ force: true }, exec)
  assert.ok(captured, 'jobs.start was called')
  assert.equal(typeof captured!.owner, 'string', 'owner must be the SessionId string')
  assert.equal(captured!.owner, 'session-42')
  assert.equal(captured!.kind, 'graphlint-build')
  assert.match(String(captured!.label), /--force/)
})

test('graphlint_build omits the owner when the session id is unavailable', async () => {
  let captured: Record<string, unknown> | undefined
  const mounted = mount({
    jobStart: (spec) => {
      captured = spec
      return 'job-9'
    },
  })
  await mounted.definitions.get('graphlint_build')!.execute({}, execution())
  assert.equal(captured!.owner, undefined)
})

test('a refusing job registry terminates the spawned build instead of leaking it', async () => {
  let terminated = false
  const spawns: string[] = []
  const ctx = {
    tools: { register: () => () => {} },
    subprocess: {
      async resolveExecutable() { return 'graphlint.exe' },
      spawn(spec: { argv: readonly string[] }) {
        spawns.push(spec.argv.join(' '))
        return {
          done: Promise.resolve({ exitCode: 0, signal: null }),
          collected: undefined,
          terminate: () => { terminated = true },
        }
      },
    },
    fs: { resolve: async () => undefined, stat: async () => undefined },
    skills: { register: () => () => {} },
    jobs: { start: () => { throw new Error('background job limit reached for this owner') } },
    timer: { timeout: () => () => {} },
  } as unknown as PluginContext
  let execute: ToolDefinition['execute'] | undefined
  ;(ctx.tools as { register: (d: ToolDefinition) => () => void }).register = (definition) => {
    if (definition.name === 'graphlint_build') execute = definition.execute
    return () => {}
  }
  apply(ctx)
  assert.ok(execute, 'graphlint_build mounted')
  const value = await execute!({}, execution({ id: 's-1' })) as Record<string, JsonValue>
  assert.match(String(value.error), /job limit/)
  assert.equal(terminated, true, 'the spawned process tree must be terminated')
  assert.equal(spawns.length, 1)
})
