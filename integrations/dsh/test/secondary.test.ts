import assert from 'node:assert/strict'
import test from 'node:test'

import { secondaryDirs, type ServiceLookup } from '../src/secondary.js'

const ws = 'X:/workspace'

test('secondaryDirs: absent or incompatible service is a silent no-op', async () => {
  assert.deepEqual(await secondaryDirs({ get: () => undefined }, ws), [])
  assert.deepEqual(await secondaryDirs({ get: () => null }, ws), [])
  assert.deepEqual(await secondaryDirs({ get: () => ({}) }, ws), [])
  assert.deepEqual(await secondaryDirs({ get: () => ({ list: 'not-a-function' }) }, ws), [])
  assert.deepEqual(await secondaryDirs(undefined, ws), [], 'a context without ctx.get degrades to no extra roots')
  assert.deepEqual(await secondaryDirs({}, ws), [])
})

test('secondaryDirs: failing or malformed list degrades silently', async () => {
  const throwing: ServiceLookup = {
    get: () => ({
      list: async () => {
        throw new Error('boom')
      },
    }),
  }
  assert.deepEqual(await secondaryDirs(throwing, ws), [])
  assert.deepEqual(await secondaryDirs({ get: () => ({ list: async () => 'not-an-object' }) }, ws), [])
  assert.deepEqual(await secondaryDirs({ get: () => ({ list: async () => ({}) }) }, ws), [])
})

test('secondaryDirs: returns sanitized configured directories', async () => {
  const ctx: ServiceLookup = {
    get: () => ({ list: async () => ({ dirs: ['D:/sec', '', 42, null, 'D:/sec2'] }) }),
  }
  assert.deepEqual(await secondaryDirs(ctx, ws), ['D:/sec', 'D:/sec2'])
})

test('secondaryDirs: probes the multiFolder service with the session workspace', async () => {
  const probed: string[] = []
  const asked: unknown[] = []
  const ctx: ServiceLookup = {
    get(name: string) {
      probed.push(name)
      return {
        list(workspace: string) {
          asked.push(workspace)
          return { dirs: [`${workspace}/sec`] }
        },
      }
    },
  }
  assert.deepEqual(await secondaryDirs(ctx, ws), [`${ws}/sec`])
  assert.deepEqual(probed, ['multiFolder'], 'the probe reads the multiFolder service by name')
  assert.deepEqual(asked, [ws], 'the service is asked about THIS session workspace')
})

test('secondaryDirs: tolerates a synchronous list result and a this-bound service', async () => {
  const service = {
    fallback: ['D:/sync'],
    list(workspace: string) {
      return { dirs: [`${workspace}/sec`, ...this.fallback] }
    },
  }
  const ctx: ServiceLookup = { get: () => service }
  assert.deepEqual(await secondaryDirs(ctx, ws), [`${ws}/sec`, 'D:/sync'])
})
