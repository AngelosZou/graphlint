import type { PluginContext, SkillRegistration } from './types.js'

const GRAPHLINT_SKILL: SkillRegistration = {
  name: 'graphlint',
  description: 'Dead-code detection for AI-generated codebases via the graphlint dependency-graph analyzer.',
  whenToUse:
    'After code modifications, or before analyzing a codebase, to find dead code, circular references, unused imports and other warnings.',
  invocation: { modelInvocable: true, userInvocable: true },
  content: `# graphlint — dead code detection

## When to use
- After code modifications: check whether your edits left dead or redundant code (components unreachable from any entry point).
- Before analyzing a codebase: understand whether a feature is well integrated.

## Tools
- graphlint_query — query the dependency graph (fast incremental mode; auto-rebuilds the index when files changed).
- graphlint_build (force: true) — full index rebuild as a background job; poll with job_output. Only needed for a fresh checkout or after many changes.
- graphlint_config — show/get/set the project's .graphlint/config.json, e.g. add custom entry rules matching framework conventions.

## Key parameters (graphlint_query)
- root_dir — project root. MUST stay inside the session working directory (the default). Scanning a high-level root builds a huge index and can block for many minutes.
- warn_types — comma-separated filter, e.g. dead_code, circular_ref, unused_import.
- include_tests / public_as_entry / graph_id.

## Limitations
Static analysis only: dynamic references (getattr, importlib, reflection, DI containers) can produce false positives. Mitigate by adding custom entry rules for your conventions via graphlint_config.
`,
}

export function registerGraphlintSkill(ctx: PluginContext): void {
  ctx.skills.register(GRAPHLINT_SKILL)
}
