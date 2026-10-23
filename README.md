# Termi package builds

**Catalog status: building, not yet available in the app.** Candidate releases
are unsigned build evidence. They are not production APT repositories or APKs.

Public zero-cost Actions/Release pipeline for packages built for `com.terminal.nextgen`, not stock Termux binaries.

See [pipeline and limits](docs/FREE_PACKAGE_PIPELINE.md). Manual workflow modes:
plan/test, selected recipes, or a resumable full-catalog batch. Candidates and
checkpoints are prereleases. No Android app data or signing secrets are included.

- [Cycle-free full-catalog run](https://github.com/MannanSaood/termi-packages/actions/runs/40008937527)
- [Live full-catalog progress](https://github.com/MannanSaood/termi-packages/releases/tag/progress-40008937527-1)
- [PulseAudio module source verification](https://github.com/MannanSaood/termi-packages/actions/runs/40008824612)
- [Node/npm run](https://github.com/MannanSaood/termi-packages/actions/runs/40003582122)
- [Successful hello source build](https://github.com/MannanSaood/termi-packages/actions/runs/40001467035)

New source runs publish a `progress-RUN_ID-ATTEMPT` prerelease while compilation
is running (created after preparation). Refresh that page for counts and download
`progress.json`, `failures.log` or `current.log`. Updates are approximately once
per minute. Completed recipes/requested roots and candidate Debian files are
separate counts. Failure/current log tails are bounded; no package is thereby
approved. Old workflows already running cannot gain these changes retroactively.

Already signed metadata has a separate, manually dispatched Pages deployment
workflow. It verifies existing Termi signatures and expiration and cannot sign
or approve packages. Public package binaries live in Releases; Pages contains
metadata only. The optional Cloudflare Worker uses the Free plan, without R2.
