# Zero-cost package pipeline — 2026-10-23

Owner constraint: no paid services, paid runners, paid cache expansion, domain
purchase or R2 charges. Separate public repository authorized and created:
https://github.com/MannanSaood/termi-packages . This supersedes the earlier paid
object-store/builder recommendation while the zero-cost constraint applies.

## Infrastructure and what the owner needs to provide

| Purpose | $0 implementation | Owner action |
|---|---|---|
| Source and automation | Public `termi-packages` repository | Created with the existing GitHub authorization; keep it public. |
| Linux builds | Standard public GitHub Actions Ubuntu runner | Enable/approve Actions if GitHub prompts. No paid/larger runner labels. |
| Packages and sources | Immutable GitHub Release asset batches | No separate storage account. Each asset must be under2GiB; batches reserve capacity below1000assets. |
| Large compile checkpoints | Compressed container export split into1GiB release assets | No paid cache. Each restore needs its manifest hash and complete build-input identity. |
| Small signed APT metadata | GitHub Pages, separate main/root/X11 namespaces | Enable Pages when the first reviewed signed snapshot is ready. Keep only metadata there, below1GB. |
| Normal APT paths to release downloads | Cloudflare Workers Free redirector at a free `workers.dev` hostname | A free Cloudflare account and Workers Free access. No R2, custom domain, KV, database or paid Worker plan. |
| Repository signatures | Existing isolated Termi signing authority | No new signing key needed. Private root stays offline; no key or phone data is published. |

The Worker is prepared, not deployed. Authenticate Cloudflare through its normal
local/dashboard flow; do not paste API secrets into chat. Free Workers have a
100,000request/day account limit and10ms CPU/request. Package bytes go directly
from GitHub after302, so the Worker does not proxy or store large files.
When a free quota is exhausted the service must fail/report it, not upgrade to
a paid plan. [Workers limits](https://developers.cloudflare.com/workers/platform/limits/).

GitHub documents free standard runners for public repositories,4CPU/16GBRAM/
14GBSSD for Ubuntu and a6hour per-job limit. Larger runners are not free.
The workflow only runs when the repository is public and uses `ubuntu-24.04`.
It measures disk and reclaims listed unused preinstalled SDKs only on the
disposable GitHub-hosted Linux VM. Actual recovered space must be measured;
there is no guarantee every recipe fits.
[Runner specs](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[time limits](https://docs.github.com/en/actions/reference/limits),
[larger-runner pricing rule](https://docs.github.com/en/billing/reference/actions-runner-pricing).

GitHub Releases allow up to1000assets/release, under2GiB each, with no stated
total-release size/bandwidth limit. This is for this project's actual packages,
sources and necessary build checkpoints; not unrelated general backup storage.
Do not commit the binary pool to Git or put it all on Pages. Do not use paid
cache expansion or private Actions/artifact allowances as an implicit fallback.
[Release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases),
[Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits),
[cache billing](https://github.blog/changelog/2025-11-20-github-actions-cache-size-can-now-exceed-10-gb-per-repository/).

## Why the redirector is needed

An actual isolated Linux APT probe rejected a full `https://...` Filename in a
signed Packages index: it appended it to the repository root. Do not claim that
direct absolute GitHub URLs in that field work. A relative signed path such as
`pool/termi-main-<batch-hash>/nodejs_26.4.0-1_aarch64.deb` successfully followed a
release-style302 redirect and downloaded exact checksum-verified fixture bytes.
This is host APT coverage; the real Android APT/HTTPS/Worker path still needs a
connected test. The negative absolute-URI probe is retained as a regression test.

`edge/worker.mjs` restricts metadata paths and fixed GitHub owner/repository;
supports GET/HEAD; rejects cross-channel/traversal routes; preserves escaped
epoch filenames; gives immutable paths long caching and mutable signed metadata
`no-store`. It never receives a private repository or signing credential.
Three Node tests cover those paths. `release_plan.py` assigns deterministic
batches, reuses existing locations only for identical approved bytes, and changes
the inventory hash before review/signing. Publisher signs the relative paths,
compressed/plain indexes and Acquire-By-Hash objects under the retained authority.

## Heavy recipes and checkpoints

The free workflow reserves two hours of a6hour job for setup/checkpoint work,
with an individual compile deadline of4hours. A stopped, unprivileged, mount-free
builder can be exported without creating another whole Docker image on disk.
Streaming gzip writes one1GiB temporary part at a time, uploads it as a release
asset, then removes only that temporary part. The checkpoint manifest is uploaded
last. A failed partial upload cannot be restored without its final manifest.

Restore verifies the explicit manifest SHA256, each part's byte count/hash and
the exact build-input hash, and imports only into an isolated Docker image.
No archive extraction takes place on the host. Source/prefix/patch JSON and the
restored image label must match the newly prepared context before compilation.
No GH token, host directories or phone data enter the package builder container.
These are build caches, never approved runtime packages or a replacement for
the signing authority.

Use upstream `-c` only when the selected recipe was interrupted during make or
later. Host builds/configure/installer steps are not universally resumable this
way. The workflow accepts an explicit `continue_recipe`; it does not guess that
every timeout is safe to resume. Input changes invalidate the checkpoint.
Small part-streaming tests pass, but full multi-hour GitHub save/restore and every
heavy recipe have not been certified. A recipe that exceeds available memory or
disk remains BLOCKED until it is restructured or a legitimately available free
machine can build it. Checkpointing solves elapsed-time continuity, not unlimited
RAM/disk. No promise that every upstream recipe fits standard free runners.

An existing/donated Linux computer may be an additional self-hosted builder at no
new hosting cost if the owner has one. It is not assumed available. Do not create
multiple accounts to evade quotas or silently rent a VM/larger runner.

## Full graph and current source blockers

The pinned graph accounts for3,268parentrecipes and6,955provided package aliases,
including upstream's virtual static aliases; one recipe is architecture-excluded.
This is not a count of already built debs. The bounded source-dependency analysis
initially found three groups before honoring upstream runtime-only anti-build
annotations. Those annotations remove the two .NET metapackage cycles from the
compile order without removing their runtime dependencies. One genuine source
cycle remains:

- `libmp3lame`, `libmpg123`, `libsndfile`, `pulseaudio`.

This requires verified source-built bootstrap stages. It cannot be resolved by
the forbidden stock Termux binary/cycle fallback. The ledger records cycle
members, failed builds and dependency blockers, while allowing independent
recipes to build. It preserves completed recipes across retries and rejects
changed build identities. The first upstream full-order check failed and entered
its expensive cycle printer; it was stopped. The new bounded graph reports the
actual groups rather than hiding or claiming them resolved.

The collector records parent recipe/channel using that graph. Main/root/X11
snapshots stage and validate separately; optional channels can depend on main,
but are not silently mixed into main. Root/X11 execution requirements still need
their actual integrations. No entire-catalog availability or runtime pass follows
from a successful graph export, synthetic ledger test, or candidate CI run.

## Current verification boundary

Local Linux suite31tests PASS, including real signed APT relative/redirect
download, the expected rejection of absolute Filename URLs, channel separation,
ledger retries/blockers, immutable versions, compressed signed indexes and chunk
streaming. Worker3tests PASS. Shell workflow blocks parse. Phone unavailable;
no data access/install/clear/rollback. Live APK and existing proof APT endpoint
remain unchanged. Remote workflow results and real heavy checkpoint verification
are recorded in the handover as they become available.
