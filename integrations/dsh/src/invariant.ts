/**
 * Package-owned invariant companion, mirroring the official @deepseek-ai/*
 * pattern: registers the package name so lifecycle relation checks can
 * attribute resources to this plugin. No runtime invariant is installed.
 */

const PACKAGE_NAME = '@angeloszou/dsh-graphlint'

export const name = 'dsh-graphlint-invariant'

export const inject = ['invariants']

const install = () => {}

export function apply(ctx: { invariants: { register(packageName: string, installer: () => void): () => void } }) {
  return Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install))
}
