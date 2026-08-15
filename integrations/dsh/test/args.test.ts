import assert from 'node:assert/strict'
import test from 'node:test'

import { buildArgv, configArgv, queryArgv } from '../src/args.js'

const EXE = 'graphlint'

test('queryArgv: base invocation forces json, english and root-dir', () => {
  assert.deepEqual(queryArgv(EXE, { rootDir: 'C:\\proj' }), [
    EXE,
    'query',
    '--json',
    '--lang',
    'en',
    '--root-dir',
    'C:\\proj',
  ])
})

test('queryArgv: maps every optional flag', () => {
  assert.deepEqual(
    queryArgv(EXE, { rootDir: 'C:\\proj', warnTypes: 'dead_code,circular_ref', includeTests: true, graphId: 7, publicAsEntry: true }),
    [
      EXE,
      'query',
      '--json',
      '--lang',
      'en',
      '--warn-types',
      'dead_code,circular_ref',
      '--include-tests',
      '--public-as-entry',
      '--graph-id',
      '7',
      '--root-dir',
      'C:\\proj',
    ],
  )
})

test('queryArgv: skips a blank warn_types', () => {
  assert.deepEqual(queryArgv(EXE, { rootDir: '.', warnTypes: '  ' }), [EXE, 'query', '--json', '--lang', 'en', '--root-dir', '.'])
})

test('queryArgv: maps exclude_clean', () => {
  assert.deepEqual(queryArgv(EXE, { rootDir: '.', excludeClean: true }), [
    EXE,
    'query',
    '--json',
    '--lang',
    'en',
    '--exclude-clean',
    '--root-dir',
    '.',
  ])
})

test('buildArgv: has no root-dir flag; root comes from cwd', () => {
  assert.deepEqual(buildArgv(EXE, false), [EXE, 'build', '--lang', 'en'])
  assert.deepEqual(buildArgv(EXE, true), [EXE, 'build', '--lang', 'en', '--force'])
})

test('configArgv: show takes no params', () => {
  assert.deepEqual(configArgv(EXE, 'show'), [EXE, 'config', '--lang', 'en', 'show'])
})

test('configArgv: get passes the key', () => {
  assert.deepEqual(configArgv(EXE, 'get', { key: 'lang' }), [EXE, 'config', '--lang', 'en', 'get', '--key', 'lang'])
})

test('configArgv: set passes key and value', () => {
  assert.deepEqual(configArgv(EXE, 'set', { key: 'lang', value: 'en' }), [
    EXE,
    'config',
    '--lang',
    'en',
    'set',
    '--key',
    'lang',
    '--value',
    'en',
  ])
})

test('configArgv: add-entry-rule passes rule-json', () => {
  assert.deepEqual(configArgv(EXE, 'add-entry-rule', { ruleJson: '{"name":"x"}' }), [
    EXE,
    'config',
    '--lang',
    'en',
    'add-entry-rule',
    '--rule-json',
    '{"name":"x"}',
  ])
})

test('configArgv: remove-entry-rule passes name', () => {
  assert.deepEqual(configArgv(EXE, 'remove-entry-rule', { name: 'x' }), [
    EXE,
    'config',
    '--lang',
    'en',
    'remove-entry-rule',
    '--name',
    'x',
  ])
})

test('configArgv: add-exclude and remove-exclude pass exclude-pattern', () => {
  assert.deepEqual(configArgv(EXE, 'add-exclude', { excludePattern: '*/gen/*' }), [
    EXE,
    'config',
    '--lang',
    'en',
    'add-exclude',
    '--exclude-pattern',
    '*/gen/*',
  ])
  assert.deepEqual(configArgv(EXE, 'remove-exclude', { excludePattern: '*/gen/*' }), [
    EXE,
    'config',
    '--lang',
    'en',
    'remove-exclude',
    '--exclude-pattern',
    '*/gen/*',
  ])
})
