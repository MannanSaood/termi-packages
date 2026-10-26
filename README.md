# Termi package builds

**Catalog status: building, not yet available in the app.** Candidate releases
are unsigned build evidence. They are not production APT repositories or APKs.

Public zero-cost Actions/Release pipeline for packages built for `com.terminal.nextgen`, not stock Termux binaries.

See [pipeline and limits](docs/FREE_PACKAGE_PIPELINE.md). Manual workflow modes:
plan/test, selected recipes, or a resumable full-catalog batch. Candidates and
checkpoints are prereleases. No Android app data or signing secrets are included.

- [Cycle-free full-catalog run](https://github.com/MannanSaood/termi-packages/actions/runs/40075636176)
- [Live full-catalog progress](https://github.com/MannanSaood/termi-packages/releases/tag/progress-40075636176-1)
- [PulseAudio module source verification](https://github.com/MannanSaood/termi-packages/actions/runs/40071625921)
- [Node/npm run](https://github.com/MannanSaood/termi-packages/actions/runs/40003582122)
- [Successful hello source build](https://github.com/MannanSaood/termi-packages/actions/runs/40001467035)

Latest completed full batch: **119 completed recipes / 128 candidate Debian files**. Audio source build passed. The full build hit a read-only Go-cache cleanup regression; the fix passed 44 tests, and continuation retains 119 recipes / 127 files while rebuilding docker-cli. Node/npm source build succeeded; phone runtime checks remain pending.

New source runs publish a `progress-RUN_ID-ATTEMPT` prerelease while compilation
is running (created after preparation). Refresh that page for counts and download
`progress.json`, `failures.log` or `current.log`. The page updates approximately
once per minute; downloadable snapshots update every5minutes and at completion
to conserve the shared free GitHub API budget. Completed recipes/requested roots and candidate Debian files are
separate counts. Failure/current log tails are bounded; no package is thereby
approved. Old workflows already running cannot gain these changes retroactively.

Already signed metadata has a separate, manually dispatched Pages deployment
workflow. It verifies existing Termi signatures and expiration and cannot sign
or approve packages. Public package binaries live in Releases; Pages contains
metadata only. The optional Cloudflare Worker uses the Free plan, without R2.



Parallel source builds are now active: [lane0](https://github.com/MannanSaood/termi-packages/actions/runs/40077675224),
[lane1](https://github.com/MannanSaood/termi-packages/actions/runs/40077677670),
[lane2](https://github.com/MannanSaood/termi-packages/actions/runs/40077679803),
[lane3](https://github.com/MannanSaood/termi-packages/actions/runs/40077681910).
[Ecj API26 verification](https://github.com/MannanSaood/termi-packages/actions/runs/40077684257) is pending.
Each lane uses its own installed prefix and includes its dependencies. Counts
across lanes overlap: use the pinned candidate merge tool for unique totals.
Lane pages update every5minutes; downloadable snapshots every25minutes/final.
The original sequential run remains active to preserve in-flight compilation.

Latest verified union: **868 completed recipes / 1175 candidate Debian files**;
2400 eligible recipes remain, plus one architecture exclusion. Candidate
[candidate-40096038350-1-0](https://github.com/MannanSaood/termi-packages/releases/tag/candidate-40096038350-1-0)
preserves explicit source pins and independently rebuilt archive variants.
Restarted lanes with first-wave recipe repairs:
[lane0](https://github.com/MannanSaood/termi-packages/actions/runs/40097207575),
[lane1](https://github.com/MannanSaood/termi-packages/actions/runs/40097209962),
[lane2](https://github.com/MannanSaood/termi-packages/actions/runs/40097212869),
[lane3](https://github.com/MannanSaood/termi-packages/actions/runs/40097215014).
Ecj/audio source builds passed. New repairs await actual compiler results;
fortune source-host availability remains unresolved. Nothing is runtime-approved.

Fortune's source outage is resolved by an exact-checksum Freetz source mirror;
the separate Debian source-data URL is also repaired with its original checksum.
[Focused fortune verification](https://github.com/MannanSaood/termi-packages/actions/runs/40098113770)
is running; no Android runtime approval implied. Latest live lower bound871
unique completed recipes (868 saved plus etsh/hunspell-en-us/hunspell-ru);
shared dictionary completions are counted once. See pipeline notes for snapshot
method and timing. Existing catalog lanes continue without cancellation.

Eight-lane rounds use lane-0-of-8 through lane-7-of-8, with distinct root ownership and selected heavy roots spread across lanes. Dependency closures can overlap; a shared verified Termi seed avoids rebuilding completed dependencies. Unchanged failed recipes survive seed merging/import and require a source-input fix or explicit retry. Standard public GitHub-hosted runners only; compilation remains five hours within a six-hour job.
