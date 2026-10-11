# dsh-graphlint

DeepSeek Harness plugin bundle for [graphlint](https://github.com/AngelosZou/graphlint) —
dead-code detection for AI-generated codebases.

Installing this bundle gives every agent in the profile three tools
(`graphlint_query`, `graphlint_build`, `graphlint_config`) plus a `graphlint`
skill describing when and how to use them.

## Requirements

- Node.js >= 20.
- A DeepSeek Harness profile (`dsh plugin` initializes one on first use).
- The graphlint CLI on `PATH` (`pip install graphlint`) or inside the project's
  virtualenv (`env/`, `.venv/`, `venv/` are probed automatically).

### Supported DSH core

The bundle imports `defineTool` from `@deepseek-ai/dsh-tools` at runtime — an
out-of-tree plugin resolves it from the running installation (it is one of the
plugin manager's protected modules) — and type-checks its tool definitions
against it. Declared compatibility:

| Package | Range |
|---------|-------|
| `@deepseek-ai/dsh-tools` | `>=0.1.0-rc.6 <0.3` |
| `@deepseek-ai/cordis` | `>=4.0.5-alpha.1 <5` |

Development and CI compile against the exact published versions pinned in
`devDependencies` (currently the `0.2.1-alpha.2` core), so a contract change in
any seam the plugin consumes (`ctx.tools`, `ctx.subprocess`, `ctx.fs`,
`ctx.skills`, `ctx.jobs`, `ctx.workingDirectory`, `ctx.timer`) fails the build
instead of failing a live tool call. Bump the pins with the core.


## Install

Install the published bundle into a DeepSeek Harness profile:

```bash
dsh plugin --profile web add dsh-graphlint

# or via the graphlint CLI (requires dsh on PATH):
graphlint install dsh --profile web
```

Then restart the profile (and refresh the browser page). The bundle's patch
layer inserts the plugin row at the profile root; you can address it by id
`dsh-graphlint` in your own `cordis.patch.yml` (e.g. to disable it per profile).

Development / repository install (linking a local checkout):

```bash
# 1. Clone the repository and build the bundle
git clone https://github.com/AngelosZou/graphlint.git
cd graphlint/integrations/dsh
npm install
npm run build

# 2. Link the bundle into a profile (run from the repository root)
cd ..
dsh plugin --profile web add link:./integrations/dsh

# 3. Restart dsh web
```

## Tools

| Tool | Purpose |
|------|---------|
| `graphlint_query` | Query the dependency graph for dead code, unused imports, write-only variables, and other warnings. Fast incremental mode; JSON result. Common filters: `warn_types`, `graph_id`, `exclude_clean`, `include_tests`, `public_as_entry`. |
| `graphlint_build` | Full or incremental index rebuild as a **background job** (poll with `job_output`). |
| `graphlint_config` | `show` / `diff` / `get` / `set` entries in the project's `.graphlint/config.json`, plus `add-entry-rule` / `remove-entry-rule` / `add-exclude` / `remove-exclude` for custom entry rules and excludes. `diff` reports how the config differs from the shipped default rule template. |

The `graphlint` skill leads with these tools (they run inside the session working
directory and return structured results); the canonical CLI guidance follows as
reference.

### `root_dir` restriction

Every tool accepts an optional `root_dir`. It **must stay inside the session
working directory** (the default) — a hard guard rejects anything else with a
clear error. Scanning a high-level root (such as a user home directory) makes
graphlint build a huge first-time index and can block for many minutes.

The default root comes from the `workingDirectory` service (the seam that owns
a session's effective directory and repairs a deleted project), falling back to
the session header's original `cwd` and then to the harness process directory.
`graphlint_query` and `graphlint_config` then pass `--root-dir`; `graphlint_build`
and `graphlint config` run the CLI with that directory as their working
directory, because those subcommands read their own cwd.

### Optional Secondary working directories (`dsh-multi-folder`)

When the [dsh-multi-folder](https://github.com/AngelosZou/dsh-multi-folder)
plugin is installed and the user has configured secondary working directories
for the session, those directories automatically become valid `root_dir`
values for all three tools: the analysis root is accepted inside any configured
secondary directory, graphlint runs with that directory as its working
directory, and the index lands in its `.graphlint/`. A relative `root_dir`
still resolves against the primary session workspace.

This compatibility is automatic and optional. Each tool probes
`ctx.get('multiFolder')` at call time and nothing else changes:

- multi-folder absent, unconfigured, incompatible, or throwing → the plugin
  behaves exactly as if it did not exist (the guard falls back to the session
  working directory, and the refusal message keeps its original wording);
- multi-folder present → a refusal still names the configured secondary
  directories and the `/multi-folder` command that adds one, so the model
  learns the valid roots instead of retrying blindly.

The `multiFolder` service and the `workingDirectory` service are both optional
seams, read through `ctx.get` and never declared in `inject`, so neither plugin
becomes a hard dependency of the other.

## Development

```bash
cd integrations/dsh
npm install          # first time only; afterwards npm ci
npm run build        # generate-skill.mjs + tsc → lib/
npm test             # node --test lib/test/
```

Type-checking is part of `npm run build`, and the seam types come from the real
`@deepseek-ai/*` packages rather than hand-written copies — build failure is the
signal that a core contract moved. `src/types.ts` re-exports them and narrows
the two optional seams; nothing in `src/` restates an engine-shaped service a
second time.

The test suite covers the pure logic layers (root guard, argv construction, JSON
parsing), the optional multi-folder probe and its end-to-end tool wiring (root
resolution and spawned CLI cwd, with and without the peer plugin), the
`workingDirectory` root resolution and its fallbacks, the background-job owner
type, and manifest/patch contract checks. A committed `package-lock.json` is
required (CI runs `npm ci`).

If the sandbox forbids the Node test runner's per-file child processes
(`spawn EPERM` on a Windows confined run), run the same suite in one process:

```bash
node --test --experimental-test-isolation=none "lib/test/**/*.test.js"
```

