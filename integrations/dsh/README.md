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

## Install

Install the published bundle into a DeepSeek Harness profile:

```bash
dsh plugin --profile web add dsh-graphlint
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
| `graphlint_query` | Query the dependency graph for dead code, circular refs, unused imports, and other warnings. Fast incremental mode; JSON result. |
| `graphlint_build` | Full or incremental index rebuild as a **background job** (poll with `job_output`). |
| `graphlint_config` | `show` / `get` / `set` entries in the project's `.graphlint/config.json`. |

### `root_dir` restriction

Every tool accepts an optional `root_dir`. It **must stay inside the session
working directory** (the default) — a hard guard rejects anything else with a
clear error. Scanning a high-level root (such as a user home directory) makes
graphlint build a huge first-time index and can block for many minutes.

## Development

```bash
cd integrations/dsh
npm install          # first time only; afterwards npm ci
npm run build        # tsc → lib/
npm test             # node --test lib/test/
```

The test suite covers the pure logic layers (root guard, argv construction,
JSON parsing) plus manifest/patch contract checks. A committed
`package-lock.json` is required (CI runs `npm ci`).
