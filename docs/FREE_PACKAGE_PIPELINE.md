# Zero-cost package pipeline — 2026-10-23

**Hosting selection,2026-10-24:** owner selected local hosting for now and
deferred Workers. Tested server code is in [the main Termi repo's local folder](https://github.com/MannanSaood/termi/tree/main/local),
commit `11cbf77`. The Windows LAN server currently serves the existing63reviewed
packages at `http://192.168.1.5:8765/apt/main/`; full catalog builds continue on
GitHub. No Cloudflare account/action is needed at this stage. The Worker setup
below remains a future option, not a current hosting prerequisite. The app's
source settings have not been changed, and physical phone reachability remains
untested. See `local/README.md` in the app repo for start/stop and limitations.

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
| Small signed APT metadata | GitHub Pages, separate main/root/X11 namespaces | Pages is configured for workflow deployment. Publish the first reviewed signed metadata snapshot; no further storage account needed. |
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

The pinned upstream graph accounts for3,268parentrecipes. Termi adds one
source-built `mpg123-pulse` recipe, making3,269recipes and6,957provided package
aliases including upstream's virtual static aliases; one recipe is
architecture-excluded.
This is not a count of already built debs. The bounded source-dependency analysis
initially found three groups before honoring upstream runtime-only anti-build
annotations. Those annotations remove the two .NET metapackage cycles from the
compile order without removing their runtime dependencies. The remaining audio
cycle was resolved on2026-10-24 using mpg123's documented component split:

- `libmp3lame`, `libmpg123`, `libsndfile`, `pulseaudio`.

The decoder libraries and player build first without output modules, retaining
PulseAudio as the default module choice. The new `mpg123-pulse` recipe builds
the output module after PulseAudio; `mpg123` depends on that exact module version
at runtime. Both use checksum-pinned mpg1231.33.7 source and revision1. Runtime
dependencies remain enforced; only runtime-only module edges are excluded from
the library's compile ordering. The regenerated complete graph has no cycles.
No stock Termux binary/cycle fallback is enabled. The ledger records cycle
members, failed builds and dependency blockers, while allowing independent
recipes to build. It preserves completed recipes across retries and rejects
changed build identities. The first upstream full-order check failed and entered
its expensive cycle printer; it was stopped. The new bounded graph reports the
actual groups. The earlier cycle is historical; Android verification of the new
module package is running separately and is not yet a runtime approval.

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

## Execution update — 2026-10-24

The separate public repository is live. Plan run
[40000802305](https://github.com/MannanSaood/termi-packages/actions/runs/40000802305)
and actual full-feature `hello` source-build run
[40001467035](https://github.com/MannanSaood/termi-packages/actions/runs/40001467035)
passed. The measured runner had86GiB free before reclaim and104GiB afterward;
this is an observation on that VM, not a guaranteed runner specification.

Whole-catalog source run
[40003577527](https://github.com/MannanSaood/termi-packages/actions/runs/40003577527)
and independent Node/npm source run
[40003582122](https://github.com/MannanSaood/termi-packages/actions/runs/40003582122)
were launched at commit `24a705c` and are still building at this checkpoint.
They use separate standard Ubuntu VMs; no phone or local full compile is needed.
No reliable whole-catalog completion date exists yet. Thousands of recipes,
dependency failures, disk and memory limits can require many days or longer.
Candidate outputs are unsigned prereleases, not an available production catalog.

The full-catalog mode now has a3.5hour internal budget,4hour outer compile
deadline,16GiB disk headroom, persistent per-recipe state and artifact export.
Remaining work returns a non-success state and is checkpointed. A continuation
uses the published checkpoint tag, manifest SHA256 and exact context identity.
Successful recipes are retained; failures/interrupted recipes are retried only
with explicit `retry_failed`, and `continue_recipe` still requires confirmation
that upstream's compile continuation is appropriate. These manual runs do not
automatically dispatch an endless build chain. A subsequent run must use the
same input commit or an explicitly reviewed fresh build; changed inputs are
rejected by the cache identity check.

Actual small Docker/GitHub checkpoint roundtrip PASS: fixture4700bytes,
release `checkpoint-transport-20261023-v1`, manifest SHA256
`8bc9060312550bfad7d595da6115a3e5ad554850c961d4a20b3051bfef9b82bb`.
Verified upload, manifest/chunk checks, streamed import, builder identity,
context label and exact restored bytes. No container was executed. Large,
multi-hour checkpoint transfers remain unverified; this does not remove RAM or
disk constraints. A valid Docker `Env:null` response was found and handled.

Latest Linux suite33tests PASS7.744s, including trusted metadata-only Pages
export, expiry rejection, changed-index rejection, and refusal of unrelated
files. Worker3tests PASS. The Pages workflow requires an exact snapshot commit,
verifies signatures with the checked-in existing Termi public key, matches the
signed inventory/index paths, checks by-hash objects and expiry, and caps the
site at512MiB. It copies no package pool or private authority to Pages. Pages is
configured with HTTPS; no signed snapshot has been deployed or app endpoint
changed. Publication does not require placing private signing keys in this repo.

Prepare a metadata-only site after package/runtime/source/license approval and
isolated signing, for example:

```sh
python3 scripts/termux/metadata_pages.py --repository /reviewed/signed-main \
  --public /new/site/public --keyring packages/termux/repository/repository-keyring.gpg
```

Commit that `public/apt/main` tree on a dedicated metadata snapshot branch in
the package repo; pass its exact commit to `termi_package_pages.yml`. Additional
channels are independently signed and verified. Updating signatures still needs
the isolated signing process; this deployment workflow cannot approve or renew
packages. Do not deploy expired snapshots or treat unsigned candidate artifacts
as release approvals. Source/license export and review must precede promotion.

The existing real Node/npm candidate merged into a118record immutable staging
snapshot and host APT resolved its runtime closure successfully. The selector
now follows APT's chosen exact versions, preserving retained old versions and
epochs. Its release layout was planned without signing/uploading those packages.
Android install/execute/remove, real HTTPS Worker transport, live source-switch
migration and owner UI review remain pending. Existing app data and APK are
untouched. The internal ID remains `com.terminal.nextgen`; visible name is Termi.

**Owner hosting action:** sign into a free Cloudflare account and enable Workers
Free with a `workers.dev` subdomain, then authenticate Wrangler locally through
its browser login. Provide the chosen public subdomain/account selection, not a
password or API secret in chat. The redirector needs no R2 bucket, paid domain,
KV, database or paid plan. GitHub repository, public Actions, Releases and Pages
configuration are already available. A donated Linux machine is optional if a
specific recipe exceeds free runner limits; none is assumed available.

## Cycle-free source build and live progress — 2026-10-24

Code commit `8a374a9` adds the mpg123 split and live telemetry. The exact source
hash is31d0e35a4ca567ec9b5ebda6c3062bb4435d6d3eacd6ef0d95cadd7854dc03ee.
Actual pinned source native Linux libraries/programs compilation PASS without
PulseAudio, confirming supported configure options and a decoder with no Pulse
link dependency. This is not Android execution proof. Official component-split
instructions: https://raw.githubusercontent.com/libsdl-org/mpg123/main/INSTALL .
Full graph verification PASS3,269recipes/6,957aliases/onearch exclusion/zero cycles;
CI now rejects a cyclic source graph. Full pipeline36Linux tests PASS7.749s,
including real Debian output counting, incomplete archive exclusion, cached
control checks, current recipe/tail, failure codes/tail bounds, explicit selected
root scope and credential-free report upload contract. Workflow syntax passes.

New runs:
- Live telemetry pilot hello:40008819921.
- Android mpg123-pulse source closure:40008824612.
- Cycle-free full catalog with live telemetry:40008937527.

Each source run creates a public prerelease named `progress-RUN_ID-ATTEMPT`.
Its body is updated approximately every60seconds, with these downloadable assets:
`progress.json`, `progress.md`, `failures.log`, `current.log`. Completed parent
recipes/requested roots and readable candidate `.deb` file counts are separate;
none means release approval. Full mode reports all catalog recipes; selected
mode explicitly counts requested roots while Debian output includes their built
dependencies. Counts include failures/interrupted/dependency blockers/exclusions,
current recipe, halt reason, observation time and build exit status. Failure
logs expose the last8192bytes per failed recipe, max100recipes/report; complete
build logs remain in retained builder/checkpoint, not silently called full logs.
Current compiler tail is also bounded. Records are source-build diagnostics only.

GitHub token remains in the outer publisher; Docker exec reads bounded progress
without a token or host mount. The compiler receives no GitHub credentials.
No paid cache/artifacts/larger runners/Workers services were added. Progress
uses ordinary public GitHub Release assets and existing contents:write permission.
Updates failing do not kill a running compiler, but cause an explicit workflow
warning/non-success after it finishes. No fake percentages, seeded builds or
claimed packages are used. `.deb` means readable candidate control archive,
not a runtime/source/license approval. Changed output files are reinspected.

Existing runs40003577527 and40003582122 stay untouched; old workflows cannot
retroactively acquire this telemetry or new source input identity. Their outputs
and diagnostics remain separate. New source inputs invalidate their checkpoint
identity intentionally. The original63package local server/app sources remain
unchanged. Workers are still deferred and the phone is unavailable.

### Rate-budget validation and replacement runs

Final tests38PASS8.660s. Live hello pilot40008819921 completed SUCCESS with one
requested root/four readable Debian files. The initial instrumented full run
showed four built recipes/one running(aerc)/four `.deb` files across3269recipes;
audio showed13dependency `.deb` files with mpg123-pulse's closure still compiling.
These were actual in-flight reads, not seeded counters. The first publishing
version replaced four assets everyminute; official API limits exposed a risk
of exhausting the shared1000requests/hour repo quota or secondary mutation
budget. Fixed commit1155c4b: page updates everyminute, assets every5minutes/final,
bounded failure/current tails inline in the page, exponential error backoff and
rate-reset-aware pause. No source compiler receives an API token. Recommended
at most two long-running instrumented batches to leave API headroom for final
asset/checkpoint publication. Limits return stale observation timestamps and
warnings, not paid fallback or fabricated fresh counts.

Only new telemetry verification runs40008937527/40008824612 were cancelled and
replaced with rate-safe full40010088115 and audio40010092102. Original full
40003577527 and Node40003582122 remain untouched. Cancelled verification-run
snapshots are historical; do not use them as active progress. New active progress
pages use progress-40010088115-1 and progress-40010092102-1 after preparation.
The publisher changes do not alter package source inputs; 35patches/zero-cycle
graph and the native exact-source verification remain valid. Android module
compilation and phone runtime approval remain pending. Workers remain deferred.

API source: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api .

### 2026-10-24 resource and audio repair

The completed run40010088115 produced95 completed parent recipes and103 readable
candidate Debian archives, then stopped at the16GiB free-disk guard. Biome2 had
failed with Rust compiler SIGKILL; it is not counted as built. Audio run40010092102
produced68 dependency archives but mpg123-pulse did not pass: libx11 could not
find sys/shm.h. These are separate run counts, not a combined unique catalog.
Node/npm source run40003582122 completed successfully; phone installation,
execution and removal remain untested while the phone is unavailable.

Commit04a290f adds libandroid-shmem source dependency/linking to libx11, revision1;
biome2 revision1 builds Cargo with one worker, LTO off,16 codegen units and no
release debug information. Standard free Actions containers use2 workers/13GiB.
After packaging, only per-recipe build/massage/tmp/package/multilib-build and
Cargo-marked src/target scratch are discarded. Source, download cache, host tools,
installed prefix, Debian archives, markers and logs remain. Failed compile
scratch is discarded too, so -c continuation is explicitly unavailable for it.

A changed-recipe/reverse-dependency check and explicit inventory/ledger/graph
SHA256 pins permit reuse of compatible prior Termi source outputs. No foreign
app prefix/toolchain/resolver or changed global compiler patch is accepted.
The sole operational global-patch exception is the post-packaging cleanup hook.
The95 previously completed recipes remain compatible;1493 changed or reverse-
dependent recipes are invalidated (none were among those95). All103 archives
were hash/control-verified and imported in a disposable Linux builder, data-only:
no maintainer scripts or Android programs executed. New live reports label reused
recipes separately. GitHub's percent-to-dot asset filename normalization is
handled only for hash-pinned input lookup. Optional future Worker epoch-file
redirects need the same normalization verified before public deployment; local
hosting remains unchanged.

Validation:43 Linux tests PASS; actual3269-recipe/6957-alias source graph has
zero cycles and one architecture exclusion; workflow bash syntax checked.
Real103-archive seed import PASS with95 recipes. These checks do not certify
Android audio execution, full catalog completion or a release APK.

Restarted source jobs:
- Full catalog: https://github.com/MannanSaood/termi-packages/actions/runs/40071623946
- Full progress (created after preparation): https://github.com/MannanSaood/termi-packages/releases/tag/progress-40071623946-1
- Audio: https://github.com/MannanSaood/termi-packages/actions/runs/40071625921
- Audio progress: https://github.com/MannanSaood/termi-packages/releases/tag/progress-40071625921-1

Both use candidate-40010088115-1-0 with explicit pins:
- inventory: d2fd3c15c05443d66dbb49ad1ca96c1ea241c14a920f97a4893f1e9633306d77
- ledger: abd54d88d23e051aa5087e0f8b798adc2599d2da74fe490c2ceca74b2c2d40a8
- plan: f5b1e7bf329ffbf85442a9dd2fb8d8cf64cf13ebb25c68707398159f90ed5f94

Do not add reused archives twice or call queued/preparing counts newly built.
No signing authority, app data, APK or local63-package reviewed repository changed.
Workers/R2 and paid runners remain deferred.

### 2026-10-24 read-only Go cache regression and audio success

Audio source run40071625921 SUCCESS: requested mpg123-pulse root1/1 and232
readable candidate Debian files (includes the103 reused files; not232 newly
compiled packages). Confirmed mpg123-pulse_1.33.7-1_aarch64.deb SHA256:
97d1392d103e6b97c69b6725d30a999e83608cbba8988ceb67032604938ed123 .
Control dependencies: libmpg123 (=1.33.7-1), pulseaudio. Android playback has not
been tested while the phone is unavailable.

Full run40071623946 reached119 completed recipes/128 candidate files, then
FAILED. Biome2 now built successfully. docker-cli itself compiled and packaged,
but the post-package cleanup hook failed deleting a deliberately read-only Go
module-cache directory. The subsequent full-catalog cleanup raised the same
PermissionError and aborted traversal. This was our cleanup regression, not a
docker-cli compiler defect. Its ledger status remains failed and its candidate
archive is excluded from reuse, rather than silently relabelled successful.

Fix3ea2310 makes only directories within validated disposable scratch owner-
accessible before deletion, without following/chmodding aliases to preserved
source/cache/host-tool paths. OSError in operational cleanup is now visible as
TERMI_SCRATCH_WARNING (and ledger scratch_warning), without falsely failing an
already successful compilation. Unsafe-target ValueError still fails closed;
normal disk headroom checks remain active.44 Linux tests PASS7.441s, including
an actual non-root read-only nested Go cache with an external symlink whose
contents and permissions remain unchanged.

Continuation https://github.com/MannanSaood/termi-packages/actions/runs/40075636176
uses source candidate candidate-40071623946-1-0. Metadata compatibility verified:
119 reusable recipes/127 archives/zero changed recipes; docker-cli is rebuilt.
Explicit pins:
- inventory64d8e5107e029dbe60a526b4f4cfb6d350e46e37d4175bdc3d06fbfd06686007
- ledger b5cddfd718c1bdc445b8e9102a5ef20899608f9de7fc7c81e3b018d99b04faab
- plan96088b46c76f9e3c9b2097e9229540641549044506fc7750e2c843ceabf9599c

Progress page after preparation:
https://github.com/MannanSaood/termi-packages/releases/tag/progress-40075636176-1 .
No app data/APK/local approved repository changes. Full catalog is incomplete;
source build success is separate from phone runtime approval.
