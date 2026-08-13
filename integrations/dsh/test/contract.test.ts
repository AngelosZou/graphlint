import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

interface PackageManifest {
  name?: string
  dsh?: { bundle?: { patch?: string } }
  exports?: Record<string, unknown>
  files?: string[]
}

const pkgUrl = new URL('../../package.json', import.meta.url)
const pkg = JSON.parse(readFileSync(pkgUrl, 'utf8')) as PackageManifest

function fileUrl(relative: string): URL {
  return new URL(`../../${relative}`, import.meta.url)
}

test('manifest declares the dsh bundle patch and the file exists', () => {
  assert.ok(pkg.dsh && typeof pkg.dsh.bundle?.patch === 'string', 'dsh.bundle.patch must be a string')
  const patchPath = pkg.dsh.bundle.patch as string
  assert.ok(existsSync(fileUrl(patchPath)), `patch file ${patchPath} must exist`)
})

test('manifest exports the default entry, invariant companion and patch file', () => {
  assert.ok(pkg.exports, 'exports map required')
  assert.ok(pkg.exports['.'], 'default export required')
  assert.ok(pkg.exports['./invariant'], 'invariant companion required')
  assert.ok(pkg.exports['./cordis.patch.yml'], 'patch file export required')
})

test('patch file inserts the plugin row', () => {
  const patchPath = pkg.dsh?.bundle?.patch
  assert.ok(patchPath)
  const text = readFileSync(fileUrl(patchPath), 'utf8')
  assert.match(text, /- insert:/)
  assert.ok(pkg.name, 'package name required')
  assert.ok(text.includes(pkg.name), 'patch must reference the package name')
})

test('package files list ships the compiled sources and the patch file', () => {
  assert.ok(Array.isArray(pkg.files), 'files list required')
  assert.ok(pkg.files.includes('lib/src'), 'files must ship lib/src')
  assert.ok(pkg.files.includes('cordis.patch.yml'), 'files must ship cordis.patch.yml')
})
