# Platforms, kernel trees, builds and boot

Design agreed in November 2026, continuing [tooling.md](tooling.md). Sections
marked **done** are implemented; **planned** is agreed but not built; **open**
still needs a decision.

## Platforms (done)

A platform is one kernel build shared by every board that names it in
`devices/<board>/device.toml` `[kernel]`. It is described in one file,
`platforms/<name>.toml`, and nowhere else:

| Field | Meaning | apple-16k / apple-4k | apple-armv7 |
|---|---|---|---|
| `arch` | `make ARCH=` | `arm64` | `arm` |
| `image` | make target and payload file | `Image.gz` | `zImage` |
| `dtbs` | where `make dtbs` leaves the boards' DTBs | `arch/arm64/boot/dts/apple` | `arch/arm/boot/dts/apple` |
| `upstream` | lock of the base the series applies to | `kernel/upstream.lock` (v7.3-rc1) | `kernel/upstream-v6.12.lock` |
| `series` | ordered patch layers | `kernel/series/<name>` | `kernel/series/apple-armv7` |
| `config` | full config | `kernel/configs/<name>/config` | `kernel/configs/apple-armv7/config` |
| `defconfig` | the same config in OrchardLinux/linux | `orchard_apple16k_defconfig`, … | `orchard_applearmv7_defconfig` |
| `branch` | its branch in OrchardLinux/linux | `main` | `armv7` |

`kernel/series.py --platform NAME` prints the checked descriptor; `kernel/build`
and orchard's kernel cache read it. A new platform is a new descriptor, not a
script. The platform layer of installed systems goes into the one arm64 root,
so it and its CI job cover only `arch = "arm64"` platforms; apple-armv7 builds
and caches, but has no platform layer until a root of its architecture exists.

**Planned:** `loader`, the payload format of the platform: `m1n1` (m1n1 +
`Image.gz` + DTBs + initramfs) or `cascadia` (trampoline + `zImage` with
appended DTB + built-in root). It follows from the kernel: m1n1 cannot run
32-bit code. How a board reaches that loader (checkm8 and Pongo, an iBoot
chain, kDFU from a jailbroken iOS) is device data and stays in
`device.toml` `[boot] methods`; whether a unit is jailbroken is detected at
runtime. The launcher takes the chain from the device and the payload format
from the platform.

## Kernel and m1n1 trees

**Done:** [OrchardLinux/linux](https://github.com/OrchardLinux/linux) (fork of
torvalds/linux) and [OrchardLinux/m1n1](https://github.com/OrchardLinux/m1n1)
(fork of AsahiLinux/m1n1). During the transition the patch layers here stay
authoritative and the trees are generated from them by
[tools/kernel-tree](../tools/kernel-tree/README.md): one commit per patch,
one merge per patch directory, the defconfigs on top, one branch per
platform base. Regeneration is stable: unchanged topics keep their SHAs.
`export.py` turns a branch into patch files for an orchard PR.

**Planned, at the switch:** the trees become authoritative and the patch
directories a generated export for one release. The kernel stays a patch
queue on top of upstream, not a fork:

- an upstream bump is a rebase onto the new tag, never a merge of upstream
  into a branch; commits that landed upstream drop out by patch-id;
- the state before a rebase stays as a tag per base (`orchard/v7.3`);
- the delta is exportable as a plain series at any time.

Configs live in the tree as defconfigs (`arch/<arch>/configs/`); orchard only
names them. Until the switch, `kernel/configs` is authoritative.

## Imported work (done)

Contributor work comes in as a layer with the original authorship and a
`kernel/sources.toml` entry, organised by subsystem, not by contributor.
Project Cascadia's A5 port is the first import from a build project rather
than a kernel tree: `tools/kernel-tree/import-cascadia.py` rebuilds the tree
its build assembles and splits it into commits whose authors come from
Cascadia's history per file. Bring-up safeguards stay out of the kernel:
storage protection is the installer's job (`runtime/recovery/storage-fence`),
and Cascadia's NAND driver is read-only by construction.

## Build arguments (planned)

1. Primitives take explicit arguments (`make PLATFORM=apple-16k`,
   `PLATFORM=all`, a producer's `--platform`) and work without orchard.
2. `orchard build` passes the same arguments through: `--platform NAME|all`,
   `--device BOARD`.
3. `orchard.local.toml` only holds sticky defaults for those arguments.
4. Precedence: argument, then `orchard.local.toml`, then the attached board,
   else an error. A local build never means all platforms implicitly; CI
   passes `--platform all`.

## Distribution builds (planned)

- A distribution builds its own inputs with its own plain command (desktop,
  root) and runs without orchard. `orchard build` in its checkout composes:
  the project's build, the platform layer, assembly.
- The platform layer (kernel, modules, DTBs, firmware recipes, initrd) is
  orchard's artifact. A distribution build takes it finished for its orchard
  revision; it is compiled locally only on request, e.g. by someone working
  on the kernel (`--kernel PATH`).
- A local test build covers one platform; releases cover all.
- The contract between a distribution and orchard is files, not Python
  imports of orchard's internals.
- One m1n1, orchard's. A distribution supplies its splash as data: an
  installed boot already reads it per entry from the boot partition; a RAM
  boot gets it over the m1n1 proxy from the launcher (to verify: earlier
  attempts at injecting it failed). Distribution m1n1 builds go away.

## Build environment (planned)

On macOS every build runs in the Podman VM, and `orchard setup` creates it
with Podman's defaults (`podman machine init`): 4 CPUs and 4 GB on a
14-core, 48 GB Mac, so one kernel build starved every other. It was raised
to 10 CPUs and 16 GB by hand (November 2026). Instead:

- `orchard setup` creates the VM with explicit resources derived from the
  host (most of its cores, a good share of its memory, a disk large enough
  for a kernel tree, a root and the builder images), and says what it chose;
- `orchard doctor` reports the VM against the host and warns when the VM is
  the bottleneck;
- the values are a visible, adjustable setting, not a default in a script;
- builds that share the VM take a job count (`ORCHARD_KERNEL_JOBS`) so a
  second build does not take every core.
- **done:** builds and launches share the component cache's lock
  (`~/.cache/orchard/.lock`); only `orchard cache` takes it exclusively, and
  an entry being built is locked on its own. Before, a build held it
  exclusively for a whole kernel compile, so an `orchard launch` of an
  already-built entry waited for an unrelated platform's build while an
  iPad sat in DFU (November 2026);
- builds check free space on the host and in the VM before they start, and
  the VM gives deleted space back (fstrim) instead of growing until a build
  dies with "no space left on device".

## Build caching (planned, last)

- Cache keys follow what determines the output (source tree, config,
  toolchain image, build flags), not the text of the scripts that run it; a
  producer change that alters output bumps an explicit producer version.
  **Done for kernels** (`KERNEL_PRODUCER`); m1n1, Pongo and the recovery tools
  still hash their scripts.
- Root and desktop as separate layers: the package base is reused while the
  package list is unchanged; a desktop change does not reinstall it.
- Package caches (pacman, apk, apt) are host directories mounted into image
  and root builds, so builder images are disposable and an interrupted build
  resumes from local disk.
- Mirrors are measured and ranked by the tooling, not hard-coded.
- `orchard cache` distinguishes what is precious (packages, downloads, git
  mirrors, firmware and private inputs), rebuildable (trees, outputs, images)
  and garbage (temporary directories), reports real sizes, and cleans only
  the last two.

## A5 boot (planned; record of how it works)

Project Cascadia's chain, as shaynelegault ran it on a P105:

1. **Pwned DFU.** checkm8 works on the A5 but needs tighter USB timing than a
   Mac can do (Cascadia uses a Raspberry Pi Pico); or kDFU: a jailbroken iOS
   (EverPwnage, iOS 7 to 9.3.6) boots a patched iBSS with `kloader`.
2. **Patched iBSS** from the user's own IPSW. For kDFU it must be
   unencrypted: after iOS has booted, the GID key is unavailable.
3. **iBEC with an auto-go hook** at fixed offsets of the iOS 8.4.1 (12H321)
   iBEC: when a Recovery-mode upload is complete, iBEC jumps into it.
4. **Staging bundle** uploaded to `0x80000000`: the `linux_boot` trampoline
   (paints status, turns MMU and caches off), padding to `0x8000`, then
   `zImage` with the DTB appended, entered at `0x80008000`. The root is built
   into the kernel: iBEC passes no initrd pointer.
5. **Linux** with a USB gadget; the host takes `10.55.0.1`, then SSH and NFS.

In orchard this is an iBoot-chain variant whose payload is the trampoline
instead of m1n1, and belongs in the launcher with the other chains:

| Cascadia | Orchard |
|---|---|
| decrypt and patch iBSS/iBEC, auto-go patch | firmware recipe steps of the device |
| `linux_boot` trampoline | built from source like m1n1, for ARM32 |
| bundle packing | the `cascadia` payload assembly of the platform |
| `irecovery -f` | the launcher's USB transport |
| DFU entry | kDFU, or an external checkm8 device |

Also needed: ARMv7 builds of the static recovery tools, the recovery
protocol for armhf, touch calibration captured once from the unit's iOS
(like `orchard capture-adt`) and handed to the boot assembly, and
shaynelegault's runtime services as a platform layer while their work moves
into drivers.

## Open

- **A5 userspace.** Distributions build one arm64 root. Recommendation:
  minimal-linux additionally builds armv7 (Alpine, also Cascadia's base) as
  the root for platforms without an arm64 root; an armv7 Omarchy (Arch Linux
  ARM `armv7h`, software rendering) stays a separate, later track.
