import type { PluginContext } from './types.js'
import { SKILL_BODY } from './skill-content.generated.js'

// The canonical skill body is embedded at build time from graphlint/skill.md
// (see scripts/generate-skill.mjs and test/skill-sync.test.ts). In the DSH
// environment graphlint is exposed as TOOLS, which are more robust than shell
// invocations, so a tool-first section leads the skill; the canonical CLI body
// follows as reference. This section is the only plugin-local content.

const DSH_INTRO = `## How to use graphlint in this environment
graphlint is exposed as tools — **prefer the tools over shelling out to the CLI**: they run inside the session working directory, return structured results, and refuse unsafe roots.

- \`graphlint_query\` — replaces \`graphlint query\`. Common arguments: \`root_dir\`, \`warn_types\` (e.g. "dead_code,unused_import"), \`graph_id\`, \`exclude_clean\`, \`include_tests\`, \`public_as_entry\`. Auto-rebuilds the index incrementally; use it after edits and before analyzing a codebase.
- \`graphlint_build\` — \`graphlint build --force\` as a **background job** (poll with \`job_output\`). Use only when \`graphlint_query\` results look wrong or stale.
- \`graphlint_config\` — \`graphlint config\` operations: \`show\`/\`diff\`/\`get\`/\`set\`, plus \`add-entry-rule\` (\`rule_json\`), \`remove-entry-rule\` (\`name\`), \`add-exclude\`/\`remove-exclude\` (\`exclude_pattern\`) for custom entry rules. \`diff\` shows how the project config differs from the shipped default rule template (which rules the user removed / added / overrode).

\`root_dir\` must stay inside the session working directory (the default) — or inside one of the session's secondary working directories when the dsh-multi-folder plugin is configured for this session. Scanning any other (high-level) root can block for minutes. Flags the tools do not expose (e.g. \`--sort-by\`, \`--fail-on\`) require running \`graphlint\` directly in a shell.

`

const GRAPHLINT_SKILL = {
  name: 'graphlint',
  description:
    'Load for codebase understanding, exploration, and modification: map the real dependency graph to separate live, reachable code from dead code, unused imports, and write-only variables, so refactors, cleanups, and deletions are safe.',
  whenToUse:
    'Use when understanding, exploring, or modifying a codebase. Before editing/refactoring/deleting or auditing code you have not fully mapped, run graphlint (via graphlint_query) to see which symbols are actually reachable from entry points; after edits, rerun it to confirm no dead or redundant code was left behind.',
  source: 'custom',
  invocation: { modelInvocable: true, userInvocable: true },
  content: DSH_INTRO + SKILL_BODY,
}

export function registerGraphlintSkill(ctx: PluginContext): void {
  ctx.skills.register(GRAPHLINT_SKILL)
}
