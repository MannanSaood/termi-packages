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

### 2026-10-24 free parallel catalog lanes and ecj repair

Commit77cac53 adds isolated catalog lanes via full-catalog mode recipes input
lane-0-of-4 through lane-3-of-4, without expanding dispatch beyond10 inputs.
SHA256(name) modulo lane count gives each parent one owner; each lane includes
its transitive dependency closure. Real graph covers3269 recipes exactly once by
ownership, zero cycles: owned797/837/820/815, closure1615/1568/1570/1694. Shared
dependencies may compile in multiple lanes. Each run has its own container,
installed prefix, ledger, progress/candidate/checkpoint releases. Checkpoint lane
mismatches are rejected. Non-owned/nondependency pending recipes are explicitly
deferred-shard, never falsely built or dropped from the graph. All lanes still
compile sources for the Termi prefix; no stock Termux Android binaries are used.

Progress pages update every300s, assets1500s/final for lanes, with observation
and publication timestamps. Counts overlap across lanes and MUST NOT be summed.
Lane Debian output uses512MiB target-size tar bundles, reducing hundreds of
concurrent API asset mutations to a handful. Future seed download accepts tar
bundles, reads only regular inventory-listed .deb members, validates namespace,
size ceilings and SHA256 before reuse; never tar.extract or package execution.

parallel_catalog.py dispatch checks public visibility and starts2–4 independent
workflow runs. merge consumes explicit inventory/ledger/plan hash pins for each
completed candidate directory, checks recipe compatibility, unions only built
parents, requires outputs, verifies package hashes, deduplicates identical files
and rejects conflicting same-name bytes. It retains source-candidate pins and
emits unique counts/new explicit hashes. No automatic signing or approval. This
is a bounded parallel batch, not a claim that the entire catalog is completed or
that all subsequent checkpoints/merge rounds run unattended. Download all lane
candidate assets then use merge --input DIRECTORY INVENTORY_SHA LEDGER_SHA
PLAN_SHA (repeat per lane) --output NEW_DIRECTORY; choose latest recipe graph
first when combining older compatible candidates. Publish merged output only as
an unsigned candidate and use its new hashes for the next dispatch. Never count
duplicates as new packages. Full merged phone/runtime validation remains pending.

Ecj original failure: D8 could not find official SDK platforms/android-26/android.jar
in pinned builder (ships24/28/35). Revision6 installs the official platform26 via
existing SDK manager if absent, requires nonempty jar, generates matching ecj-26
launcher from ecj-24 and installs it from temporary directory. Android API level
stays26. Upstream ecj recipe transforms official Eclipse JDT jar into Android DEX;
it does not compile Eclipse compiler Java sources from scratch and is not a stock
Termux binary. Ecj actual GitHub verification is pending, not reported passed.

Verification:50 Linux tests PASS17.538s (parallel-tests.log), actual full graph
ownership/dependency closure/cycles and recipe bash parsing PASS(parallel-graph.log),
workflow YAML/all bash blocks PASS, Python compileall PASS. Tests cover actual
lane-only fixture execution, cross-lane checkpoint rejection, merge dedup/conflict/
metadata pins, safe/tampered bundle extraction and existing package tests. No
local full Android build or app data access. No paid runner/artifact/cache service.
GitHub standard runners in public repositories remain free:
https://docs.github.com/en/actions/concepts/billing-and-usage
Free standard runner concurrency up to20 (account-wide limits/availability apply):
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/limits

Started at77cac53 using existing119recipe/127archive candidate and its explicit
pins recorded above:
lane0 https://github.com/MannanSaood/termi-packages/actions/runs/40077675224
lane1 https://github.com/MannanSaood/termi-packages/actions/runs/40077677670
lane2 https://github.com/MannanSaood/termi-packages/actions/runs/40077679803
lane3 https://github.com/MannanSaood/termi-packages/actions/runs/40077681910
ecj https://github.com/MannanSaood/termi-packages/actions/runs/40077684257
Progress pages use progress-RUN_ID-1 after preparation. Original sequential
40075636176 remains active deliberately to preserve in-flight work; its old ecj
failure stays historical and cannot acquire revision6 retroactively. Latest API
check: all six runs IN_PROGRESS. Four lanes plus focused ecj explain five NEW jobs;
original is sixth, not an accidentally duplicated lane. Do not claim4x throughput;
shared dependency work/preparation/checkpoint transfers reduce practical gains.

### 2026-10-24 completed batch union and repaired restart

Verified union: **868 unique completed parent recipes, 1175 candidate Debian files**.
**2400 eligible recipes remain**, plus one architecture exclusion (3269 listed).
This is source-build completion, not app availability or runtime approval.

Merge workflow40096038350 succeeded and published candidate-40096038350-1-0:
- inventory cf19285b3f0b57dda460cbfd5296c6c2cb89795514355e2a347242f219b7e10a
- ledger03c7024112c8bf714837962637e32ec210343d34a3014934f1349152e95172e2
- plan fbd31857ba630dff602ff20b31a795da8a16f80872dd938db3b7bb9bab03d852

All seven source runs are explicitly pinned in packages/termux/batch-20261024.json.
For successful selected audio/ecj runs, the merger verifies GitHub completed/
success state and derives completed parents from their pinned source inventory.
Full-lane/old sequential successes come only from their pinned built ledgers.
The union includes220 alternate independently built archive variants. Explicit
prefer-first-compatible-parent policy chooses compatible parent outputs in the
committed manifest order and records chosen/alternate SHA256 and source pins;
never calls differing bytes identical. Control/recipe/channel/original filename
conflicts still fail. Default merge policy remains strict identical-only. All
chosen bytes are verified; this is a compiler seed, not publication approval.

Initial merge40095837282 falsely appeared green because a tee pipeline masked a
metadata-pin error: duplicate byte-identical graph copies were rejected. Fixed:
set -euo pipefail, require actual release existence, and accept multiple metadata
copies only when each matches the explicitly required SHA256. The corrected run
40096038350 is the actual successful publication, not the first green badge.

Recipe repairs b94ea6c (recipe_repairs.py,74 checked preparation records):
- Exact-hash source mirrors: etsh new author domain, renameutils official release
  endpoint, all four failing hunspell dictionaries via immutable LibreOffice
  commits (original file hashes retained).
- lzop official gzip release; libgfshare original-source gzip checked against
  Debian .dsc SHA256; Ceres official2.2.0 source tag; luv source archive checksum
  matched against publisher GitHub release digest. Verification stays enabled.
- distcc/liblo retain warnings but avoid treating new NDK strtok deprecation
  annotations as compilation errors; all other error diagnostics retained.
- libfcl uses C++17 for current Eigen; RocksDB includes Android statfs header.
- libgf2x explicitly separates native compiler flags; cccc/gforth host generators
  use suitable legacy C dialects; libforestdb/mdbook-cat-prep preserve Android26
  compiler target identity despite old build code overriding the triple.
- lowdown declares/links libmd; net-snmp declares libnl/OpenSSL and source-builds
  its tiny private getsubopt compatibility archive in its own scratch rather
  than linking a deleted libnl build-tree path.
- Proton pins official Bun1.4.2 Linux HOST tool/digest as its script requires,
  without relaxing its check or copying Android binaries; Termi build label.
- lrzsz vanished development commit replaced with maintained official0.13.1
  stable release (author archive SHA256112f91059fbd118e016d800c1a5c5a1702e965d8b9bfbda6015e44e20bfb93c9).
  Five obsolete old-commit patches removed explicitly in disposable Docker
  source tree, removal audit recorded. Symbolic install aliases retained. This
  is a source-version upgrade, not a claim the old commit became reachable.
- Fortune HTTP URL corrected to HTTPS, original hash retained, but source host
  remains unavailable from probes. This external source blocker is NOT resolved.

24 recipe repair attempts, with actual compiler results pending. Three other
interrupted roots (aosp-libs/gnucap/hugo) simply need continuation/rebuild; don't
invent source fixes from a time-budget interruption. Do not call all errors fixed
before new Android-target builds finish.

Validation: actual3269 recipe graph acyclic,190 changed/reverse-dependent nodes
invalidated but **all868 completed nodes remain compatible** (repairs-graph.log).
All repaired shell scripts passed elevated Git Bash -n; Python compileall passes.
Host Python51 tests:27PASS/24POSIX skips; Docker has disappeared from this host,
so a new full Linux result is delegated to actual GitHub checks. Earlier default
Windows Temp/MSYS permission failures are historical failed checks, not passes.
Source-probe results and hashes retained under ignored android/build evidence.
Prior Linux50PASS remains historical; merger five tests PASS on actual GitHub.

Four restarted free Ubuntu catalog lanes at1e5f634, with the above union pins:
- lane0 https://github.com/MannanSaood/termi-packages/actions/runs/40097207575
- lane1 https://github.com/MannanSaood/termi-packages/actions/runs/40097209962
- lane2 https://github.com/MannanSaood/termi-packages/actions/runs/40097212869
- lane3 https://github.com/MannanSaood/termi-packages/actions/runs/40097215014

Run names now include lane labels. No old completed run restarted unnecessarily;
no extra sequential duplicate launched. Original data/APK/signing keys/local
63-package reviewed server unchanged. Standard free public Actions/Release
storage only, no paid runner/cache/R2/Worker. Owner olderAPI/highzoom deferrals
remain untested; app release/full catalog gate remains BLOCKED.

### 2026-10-24 fortune source restored and live status check

Two documented Freetz source-cache mirrors were actually downloaded successfully:
https://freetz.magenbrot.net/fortune-1.2.tar.bz2 and
https://freetz.wirsind.info/fortune-1.2.tar.bz2 . Both5224byte source archives match
the original cbb246a500366db39ce035632eb4954e09f1e03b28f2c4688864bfa8661b236a.
Found via independent Freetz fortune recipe and documented freetz_download mirror
list. No replacement implementation or compiled binaries; original file pin kept.
Recipe now uses the first mirror. Its separate fortune-mod1.99.1 SOURCE DATA
archive also verified via https://deb.debian.org/debian/pool/main/f/fortune-mod/fortune-mod_1.99.1.orig.tar.gz
(and archive.debian.org),1812089bytes, original hash
fc51aee1f73c936c885f4e0f8b6b48f4f68103e3896eaddc6a45d2b71e14eace retained.
Old http.debian.net URL replaced with working HTTPS endpoint.

Published ffce7ff; focused native Android-target verification:
https://github.com/MannanSaood/termi-packages/actions/runs/40098113770 .
This selected root has no declared dependencies, so starts without copying the
868-recipe seed. No old catalog run cancelled/restarted; existing containers
cannot acquire changed source URLs retroactively. Fortune compilation approval
awaits this real job; mirror availability/hash check is already proven.

Live snapshot cross-checks confirm at least871 unique completed parents:
868 saved plus etsh/hunspell-en-us/hunspell-ru. Lane0 869 (US dictionary), lane1
868/currentfortune, lane2 870(US+Russian), lane3 869(etsh)/currentgforth. Simply
summing new counts would double-count US dictionary. As current reporters omit
completed-name sets, the three names were reconstructed from deterministic lane
dependency order before current rank and cross-checked exactly against each
published built/failed/blocked counter. Evidence live-unique-frontier.json records
method and per-lane validity; this is a live lower bound, not a new merged ledger
or APK approval. All four snapshots building/no reported failures at observation;
overall jobs cannot be called passed while still running. Last saved union868.

Future reporters now emit completed_recipes IDs in bounded progress.json for
exact deduplicated live counts. IDs are excluded from repetitive console heartbeat
lines (as are owned_roots); no change to compiler/session contracts. Existing
active reporters cannot gain this retrospectively. Added failed/pending/running
exclusion test. Host52tests28PASS/24POSIXskips; actual GitHub checks follow. No
phone/APK/app-data/signing/local reviewed repository changes. Full catalog remains
incomplete; older-version/font-scale owner deferrals remain untested.

### 2026-10-24 resource-failure recovery (verification in progress)

Confirmed lane1 40097209962 died when the GitHub runner filesystem filled:
check-run120881856116 annotations report System.IO.IOException / No space left
on device in the runner's own diagnostic log. Consequently no final candidate
or checkpoint step ran. Its live896 completion count is not saved-package proof.
Lane0/3 stopped at the between-recipe disk guard and are exporting checkpoints;
lane2 remains active. Existing exports have not been cancelled. Fortune's focused
40098113770 job actually succeeded and published its source-built candidate.

Changes: check free disk every5seconds DURING each full-catalog recipe; below8GiB
terminate its process group, mark it interrupted with resource halt75, discard
only validated compile scratch, retain completed outputs/ledger. Between-recipe
16GiB guard remains. Disposable GitHub workflow removes the duplicate initial
context after graph/checkpoint validation. After docker build copies the verified
seed, explicit --reclaim-workflow-inputs removes duplicate .deb/.tar inputs under
GITHUB_WORKSPACE/build only (refuses aliases/outside paths; metadata retained).
Candidate publication now precedes large checkpoint export. Release staging uses
hard links instead of another byte copy. No paid runner/cache/storage introduced.
This reduces waste and prevents the observed unguarded single-recipe disk fill;
it does not establish that every heavy recipe fits a standard free runner.

Second-wave recipe attempts: GF2X HOST compiler gnu89 for its unprototyped exit()
probe; lowdown passes actual prefix includes via CFLAGS because its Makefile
omits CPPFLAGS; FCL/gnucap explicitly include float.h for DBL_MAX/DBL_EPSILON;
Gforth upstream optional Emacs bytecode install is conditional on the file being
produced, while the original equivalent gforth.el source is always installed.
No Android feature removed, API level/prefix retained. Hook matching now accepts
space before parentheses, avoiding duplicate functions for gnucap. PARI's
upstream source host times out; no working mirror/checksum substitution claimed.
Original PARI pin stays intact. Further source transport work remains pending.

Host57tests:31pass,26POSIX/tool skips. Node redirector3pass. Workflow YAML and
3inline Python blocks parse; all5generated repair Bash recipes pass bash -n.
Full pinned source context prepared with75checked patches. Docker unavailable
on Windows, so Linux57test/Android compiler verification follows on GitHub;
these five repairs are not yet claimed as successful package builds.
No phone/APK/signing/app-data or local reviewed63package repository mutation.
Full catalog/app release Gate: BLOCKED until actual build/runtime requirements.


### 2026-10-24 restart all lanes from preserved outputs

Recovery merge40114592088 actually SUCCESS; candidate-40114592088-1-0 preserves
913unique completed parents/1230Debian archives. Each source/archive hash was
checked by the merge job; prior releases/checkpoints remain intact. Source pins:
inventory858a95925cb94a4096249301ad6c1b8dbb07e5a33f69c909fecc64f313635c30,
ledgerc44f30df69c88ddcdecb82b322700bc76eae4ea782979d0923f4bd5ec24626b5,
pland516d69015edd9e59764f9b755b7b08041847297f064cd2534ccaab6aa6dddf3.
This includes the successfully built AOSP package; keep its recipe unchanged so
all lanes reuse it instead of another expensive checkout. A shallow AOSP draft
was removed before publication because it needlessly invalidated this success.

Disk changes: explicit disposable hosted mode reclaims per-recipe src/cache as
well as compile scratch after packaging/failure. Preserves host-build tools,
shared toolchains, installed prefix, built markers, output archives, logs and
published copies. After a during-recipe8GiB interruption, independent work can
continue if cleanup restores16GiB headroom; interrupted root remains explicit,
never called built. Otherwise halt75 and publish candidates before checkpoint.
Selected batches now continue independent requested roots after failure and
collect successes before returning nonzero; fixes previous lost export of the
three successful roots preceding FCL. All changes affect builder workspaces,
never phone data. Disk safeguards are not proof all heavy builds fit one free VM.

Root floating-header failure reproduced with local official NDK30 ARM64/API26:
prefix libc++/float.h include_next enters a second identical NDK wrapper; shared
include guard hides compiler definitions. -nostdinc++ removes implicit duplicate
while retaining explicit prefix C++ headers. Actual failing probe now passes.
Scope flag to FCL,gnucap,alembic,polyml,quick-lint-js,RocksDB,Pluto,Oils; do not
invalidate all saved packages via global toolchain change. FCL CMake subtree
C++11 flags also corrected to17. Hugo host-manpage CGO flags cleared and native
compiler/pkg-config explicit. gcal/recutils now declare/link real libandroid-spawn
and expose its actual header rather than mixing old gnulib's no-header fallback
with a present provider. Pluto compiler concurrency bounded to2 in both PHP
launchers; initialize link flags. Oils serial compile/verbose diagnostics.

PARI Debian original SOURCE archive5508075bytes matches original upstream pin
f317b9722eb5d9094a60303774f066f3a83e3ec1f170be8546c44d7583f30b6d.
Changed dte/diff-so-fancy/inxi archive checksums resolved by publisher tag APIs,
frozen immutable commits and per-file equality checks between commit/tag source
archives. See packages/termux/source-repairs-20261024.json; no skipped checksums.
ARPACK drops the prebuilt Android Flang runtime helper: official LLVM21.1.8 HOST
compiler with matching original source pins from the pinned flang recipe; rebuild
Fortran runtime with PIC for Termi ARM64/API26, retain LLVM license. No Termux
Android package/runtime binaries used by this new ARPACK recipe. Actual build
verification follows; source/configuration changes alone are not package PASS.

Failure progress includes bounded FIRST diagnostics plus last output so parallel
compile chatter cannot hide the root error.60hosttests32PASS/28POSIX/tools skips;
Node3PASS. All patched recipe scripts bash-nPASS. Full graph3269recipes,0cycles;
all913saved parents compatible,20non-completed recipe/dependent nodesinvalidated.
Local Docker absent; actual Linux tests/Android compilation run on public free
Ubuntu24.04 runners with2CPU/13GiB containers, no paid runner/cache/services.
No APK/app/UI/signing/app-data/local reviewed63package server mutation. Catalog
and app release gate remainBLOCKED pending actual build and runtime completion.


Restarted at158acd290ed416583973798d706db28e98c9b8f4:
- lane0 https://github.com/MannanSaood/termi-packages/actions/runs/40115673221
- lane1 https://github.com/MannanSaood/termi-packages/actions/runs/40115675323
- lane2 https://github.com/MannanSaood/termi-packages/actions/runs/40115677590
- lane3 https://github.com/MannanSaood/termi-packages/actions/runs/40115679841
Allfour IN_PROGRESS; direct jobs API confirms standard GitHub runner assigned,
job steps notyetexposed at snapshot. Do not report Linux/compilerPASS prematurely.
Pluto repair hook was actually executed on disposable originalpublisherPHPsource;
both2worker limits and linkflag initializationverified. No source downloaded by
that hook, no appoperations. Mainhandover records exactpins/evidence.


### 2026-10-25 five-hour compilation budget

Owner requested5hcompilation with1htotalheadroom beneath6hjoblimit. Changed
catalogbudget12600to18000seconds inbuild.py andcontainerfallback; workflow passes
18000explicitly. Dockerattachedprocess timeout14400to18600seconds (5h10m),
retaining10minforcontainerseedinstall/artifactcollection. WholeGitHubjob350to
360minutes. The remaininghour is total setup/publication/checkpoint overhead;
setup consumes part of that hour. Completedcandidates stillpublish BEFORE large
checkpoint export. Earlier3.5hwasconservativeforlargewholecontainerexports;
currentcachecleanupandearlycandidatepublicationallowhighercompilationallocation.
No paidrunners orhigherGitHublimit requested. YAML,inlinePython,builddriverparse
checksPASS; existing budgetterminationtest unchanged. Applies tofuture runs;
allfourpreviouslanesalreadyfinished, nooldseedrestarts/duplicatebuildsdispatched
by this configuration-only change. Preserve their1246livecompletedunion and
publishedcandidatearchives for nextmerge. Noappdata/APK/phoneoperation.


### 2026-10-25 second four-lane recovery and five-hour restart

Recovery merge40168300604 actually SUCCESS, candidate-40168300604-1-0:
1246unique completed parents/1630Debian archives, all input/outputhashes checked.
Original candidates/checkpoints remain untouched. New seed pins:
inventory7a899d9af14fab7a105e3ba4161bec6458c99e8945b60e8041c7c486e933070a,
ledgerf6c86bf8f3bc6b9b98cffddc9e5cd66a36eaca32e058879a0aab84cbfc6d3097,
planefac181b27466da99811ba0a3511eddc5093981eede31e58f625cc423d5eeff2.
The23distinct non-built roots comprise19failures and4time interruptions(guile,
wasi-libc,tinygo,zig). Retry interruptions under5h; do not call them23compilerbugs.

Prepared repairs are recorded in recipe_repairs.py/catalog_repairs.py:
- Btop/NTL QEMU loader failure: recipe-local proot invocation binds our own
  source-built AOSPopt/aosp to/system inside proot; never modifies host/system.
- Objective-C++ flags retain explicit prefix C++ headers, suppress duplicate
  implicit libc++ header and keep versionedAPI26 target. SuiteSparse/UPX/Yoga
  get the proven duplicate-header fix. Oils custom compile bypasses CPPFLAGS,
  so explicitly folds those includes intoCXXFLAGS as well as-nostdinc++.
- Restic/SCC/TDL native documentation/completion builds clear ALL cgo and target
  flags. Syncthing builds the native launcher in an isolated subshell, retaining
  original targetflags for the actual Android build.
- Own source-built LLVM Fortran runtime uses clock_gettime(CLOCK_REALTIME)
  instead ofAPI29timespec_get fallback, equivalentTIME_UTCclock onAPI26.
  SuiteSparse also builds that matching own PIC runtime instead of old target
  Flang runtime archives; LLVM license retained per consumer package.
- Stag unitprefix array inferred size retains string and terminator. Actual
  ARM64/API26compiler rejectsold[9],accepts[] under original-Werror flags.
- Gifsicle declares missinglibSM build dependency, keepinggifview. GUI Bash
  helper explicitly receives versioned C/C++ compiler targets.
- Unicode18 official UCD/Unihan republished archives downloaded, CRCverified,
  version18finalReadMe inspected, newexplicitSHA pins. Xsettingsd publisher tag
  resolved to immutablefd8029153ad2c9bcc0342b6c337034912093d6cf archive.
- Libfakekey switched from brokenYoctoURL to Debian ORIGINAL0.3+git20170516source;
  digest independently compared to .dsc. RobotFindsKitten unavailable tutorial
  fork58155... is not silently treated as available: switch tocanonical project's
  2.8284271.702originalsource, Debian .dsc hash checked, fullsourcebuiltforTermi.
  Epoch1supports upgrading fromold2022dateversion. Usesnormalautotoolsinstall,
  executableinprefix/bin, actualNKI data/manpages retained. This is an explicit
  upstreameditionchange, not an exactmirrorclaim. No prebuiltAndroidbinary.
  Source URLs/hashes/versionnotes:source-repairs-20261025.json.

Verification:60hosttests32PASS/28POSIX/toolskips; Node3PASS.105checked source
patches; full graph3269recipes,0cycles; all1246completed compatible,49affected
non-completed/dependent nodesinvalidated. AllgeneratedrecipeBashsyntaxPASS.
Actual NDK30 ARM64/API26 oldclockprobe fails, equivalentclock_gettimeprobepasses;
actualLLVMsource substitution replayed. Local Docker unavailable: actual Linux
suite and package builds verify these attempts on restartedpublicfree runners.
No blanket packagePASS before those compiler results. Existing5h/6hlimits and
source-cachecleanup remain active. No paid runner/cache/services; nooldreleases
orcheckpointsdeleted. NoAPK/signing/phone/app-data/localreviewedrepochange.
Full catalog/appreleaseGateBLOCKED pending actualcompiler/runtimecompletion.


Restarted at9e5320b withfive-hourbudget andmerged1246seed:
- lane0 https://github.com/MannanSaood/termi-packages/actions/runs/40169168330
- lane1 https://github.com/MannanSaood/termi-packages/actions/runs/40169170351
- lane2 https://github.com/MannanSaood/termi-packages/actions/runs/40169172523
- lane3 https://github.com/MannanSaood/termi-packages/actions/runs/40169174270
Latest actual snapshot: allfour IN_PROGRESS; Linuxcontract/redirectorcheckstep
SUCCESS onallfour; fullgraphverificationstep running; no failedworkflowstep.
Package compilation results remainpending. Do not call19repairs packagePASS yet.

2026-10-25 seed-import correction (supersedes the preceding active-run snapshot):
All four preceding runs failed before compilation. A relative eglinfo-system
link reaches Android /system; resolving the Linux image's /system shim produced
a false foreign-namespace rejection. Commit 76ee60a preserves that platform
boundary while still following other links and rejecting foreign app paths,
parent escapes and cycles. No recipe/archive changed; all 1,246 completed
parents / 1,630 archives and explicit merged seed pins remain preserved.
Local Python63:35PASS/28POSIX/toolskips; Node3PASS. Actual Linux contract tests
passed on all four replacements, including data-only dpkg extraction checks.
New runs with the same five-hour budget:
- https://github.com/MannanSaood/termi-packages/actions/runs/40170432183 (lane0)
- https://github.com/MannanSaood/termi-packages/actions/runs/40170433874 (lane1)
- https://github.com/MannanSaood/termi-packages/actions/runs/40170435571 (lane2)
- https://github.com/MannanSaood/termi-packages/actions/runs/40170437468 (lane3)
All four IN_PROGRESS at last check, disk reclamation active, no failed step.
Full seed import and actual new package compilation are still pending; no
additional completed packages or full-catalog PASS is claimed.

2026-10-25 next status check: all four 401704... compile steps FAILED during
seed import; workflows were saving checkpoints. Logs for lanes1/2/3 show an
absolute-path check incorrectly rejecting POSIX '//' anchors (lane0 published
traceback truncated). Correction4f6b3b5 uses is_absolute and normalizes the root;
64localtests:36PASS/28platform/toolskips. Same1246parents/1630archives preserved.
Replacements40171496962/40171498687/40171500537/40171502645 dispatched with same
seed pins and5h/6hlimits, initially pending/queued behind checkpoint preservation.
Package compilation and full import are unverified; no new completed count.
