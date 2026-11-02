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
| `loader` | the payload format its kernel boots in | `m1n1` | `cascadia` |

`kernel/series.py --platform NAME` prints the checked descriptor; `kernel/build`
and orchard's kernel cache read it. A new platform is a new descriptor, not a
script. The platform layer of installed systems goes into the one arm64 root,
so it and its CI job cover only `arch = "arm64"` platforms; apple-armv7 builds
and caches, but has no platform layer until a root of its architecture exists.

**Done:** `loader`, the payload format of the platform (validated and printed; nothing uses it yet): `m1n1` (m1n1 +
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

## Build arguments (done)

1. Primitives take explicit arguments (`make PLATFORM=apple-16k`,
   `PLATFORM=all`, a producer's `--platform`) and work without orchard.
2. `orchard build` passes the same arguments through: `--platform NAME|all`
   (repeatable), `--device BOARD`.
3. `orchard.local.toml` only holds sticky defaults for those arguments
   (`platform`, `device`, `kernel-tree`).
4. Precedence: argument, then `--device`, then `orchard.local.toml`, then the
   attached board, else an error. A local build never means all platforms
   implicitly; CI passes `--platform all`.

**Done:** `--kernel-tree PATH` builds a kernel tree of your own (a branch of
OrchardLinux/linux) with its tree's defconfig instead of orchard's patched
tree, cached apart from orchard's kernels (`kernel-tree-*`) and recorded in
`build.json`. Kernel work happens on such a branch; `export.py` turns it into
patch files at the end. It takes RAM payloads only, until distributions are
projects like any other (below).

## Projects, producers and boot (planned)

Agreed November 2026. It replaces the separate paths for RAM payloads
(`payload.toml`) and distributions (`distro.toml`): today a distribution's
build entry calls orchard's internals itself (`platform.kernel()`,
`prepare_shared()`, its own m1n1), so no orchard option (`--kernel-tree`, the
platform, the m1n1) reaches it without its own wiring.

### Three layers, each usable without the orchard CLI

1. **Producers** are plain commands, files in and files out. The kernel is
   `kernel/build` here; after the switch it is `make
   orchard_apple16k_defconfig && make` in OrchardLinux/linux. m1n1 is `make`
   in OrchardLinux/m1n1. A root is the project's own command. Instead of
   compiling, a platform's components (kernel, modules, DTBs, m1n1) can come
   from a published build with its `SHA256SUMS`. A producer may use a
   container, but never imports orchard's Python; producers exchange files
   and a small receipt (JSON) of what was built from what.
2. **Assembly** is a standalone script: m1n1, kernel, DTBs, initramfs and
   splash in, `linux.bin` out. At its core this is m1n1's payload format
   (m1n1 with DTB, `Image.gz` and initramfs appended, as Asahi documents it);
   what orchard's assembly adds beyond that (`boot.json`, several DTBs) is
   written down so it can be redone by hand.
3. **Boot** by any route: palera1n/Pongo, the m1n1 proxy, the orchard
   launcher. The commands for each are documented.

So a user can build a project's root, take or build the platform's
components, assemble and boot without orchard. The orchard CLI does what is
tedious by hand: it resolves platform and device, reuses the cache, takes
the kernel from a published build, a local build or `--kernel-tree`, runs
the producers and the assembly, and boots. `--explain` prints the plain
commands it would run, so the standalone path is documented by the tool and
cannot drift from it.

### Two stages: initramfs and root

| Stage | Job | Supplied by |
|---|---|---|
| 1: initramfs | find the root, switch to it | orchard by default: today the initrd of the platform layer (`image/platform.py` `initrd()`: BusyBox and the storage modules) for installed systems. A project may bring its own; this boundary is expected to move as the tooling does. |
| 2: root | the system | the project (a distribution's root), or orchard (the recovery/installer) |

A RAM example (`examples/minimal-boot`) is the case without a stage 2: its
`init` and `rootfs/` are packed into the initramfs (`orchard.image.initramfs`)
and nothing switches root.

The boot mode is where stage 1 gets the root from, chosen when booting, not
declared by the project:

| Mode | Root from | Chosen by |
|---|---|---|
| RAM | the whole root image, loaded with the kernel | `orchard run --root ram`; refused early if it does not fit the device's memory (device data) |
| Recovery / installer | orchard's installer system as stage 2, the release as data | the default of `orchard run` for an installable project |
| Installed | a partition on the device (BLS, read by m1n1) | `orchard launch` |
| Live | the host over USB (NBD or NFS over the gadget network), later USB storage; a tmpfs overlay makes it writable | `--root host` |

Working in an existing system (`orchard launch`, then `push`, `pull`,
`exec`) is a session with a device, not a build, and is not declared.

One root image format for every mode (ext4 or erofs, to decide) is what
makes this work: RAM, live and installed boots use the same file, so what is
tested is what is installed. A root directory remains for RAM examples and
NFS.

### The project file

One file for every project, say `orchard.toml`, replacing `payload.toml` and
`distro.toml`. It declares what the project builds and never which board it
is for; the kernel is the platform's, and a developer's choices (`platform`,
`device`, `kernel-tree`) stay in arguments and `orchard.local.toml`.

```toml
# A RAM example
name = "minimal-boot"
[root]
init = "init"
files = "rootfs"
transport = false            # no USB session helper
```

```toml
# A distribution
name = "minimal-linux"
[root]
build = "tools/build-root"   # plain command: --output DIR --arch arm64
format = "image"
[initramfs]                  # optional: a stage 1 of its own
[boot]
splash = "boot/splash.png"   # data for orchard's m1n1
cmdline = "quiet"
[release]                    # optional: installable
installer = true
```

### Carried over

- The platform layer (kernel, modules, DTBs, firmware recipes, initrd) is
  orchard's artifact. A distribution build takes it finished for its orchard
  revision and compiles it locally only on request (`--kernel-tree`).
- A local test build covers one platform; releases cover all.
- One m1n1, orchard's. A distribution supplies its splash as data: an
  installed boot already reads it per entry from the boot partition; a RAM
  boot gets it over the m1n1 proxy from the launcher (to verify: earlier
  attempts at injecting it failed). Distribution m1n1 builds go away.
- The A5 (`cascadia` loader) packs stage 1 into the zImage because iBEC
  passes no initrd. As its launcher is rebuilt from first principles, the
  aim is that it differs from arm64 only in having no m1n1; how far that
  goes is open.

### Open

- Recovery semantics: whether a distribution can bring its own recovery, or
  only data (name, splash) for orchard's.
- The root image format.
- Live boot is its own later item: the stage-1 sources (host over USB, then
  USB storage) and the launcher side.

### Order

1. Assembly as a standalone script.
2. `--explain`.
3. minimal-linux as an `orchard.toml` project.
4. omarchy-a.

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

## Updating orchard (done)

`orchard` outside a checkout runs mainline (`~/.cache/orchard/orchard-main`).
It used to fetch `main` before use when its last fetch was over ten minutes
old, so any command, even `orchard --version`, could change the code and data
a running build in another session reads. Mainline now changes only with
`orchard update`; a checkout of your own (or one `orchard.local.toml` names)
is yours to update with git. A fix for a running build means restarting it.

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
