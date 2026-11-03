# Apple Z2 touch at runtime: freezes and how to find them

What can make an `apple_z2` touchscreen stop responding after it booted, and
how to find the cause on a new board without losing the evidence. Found on
J71b (iPad 6) on 2026-11-03 (OrchardLinux/omarchy-a#25). For how the
controller boots and gets its calibration, see
[touch-calibration.md](touch-calibration.md).

## How a report is read

Generation-1 controllers (J71b, J71t, N61) raise a **level** interrupt while
reports are queued. The driver serves it in `apple_z2_gen1_drain()`, up to
four reads per interrupt. Each read (`apple_z2_read_packet()`) has two SPI
transfers:

1. **Header.** The driver sends READ_INTERRUPT_DATA (`0xeb`) with a tag. The
   controller answers `0xe1` (interrupt data) and the payload length (LE16 at
   1). Length 0 means the queue is empty.
2. **Data phase.** The driver reads that many bytes. A frame starts with
   `0xea`/`0xeb`, carries the tag (1 or 2, alternating) and a checksum. Only a
   valid frame reaches `apple_z2_dispatch_frame()` and becomes input events.

Several replies are dropped **without a log line**: a header that is not
`0xe1`, an empty queue, a control reply (`0xe1` with a valid 16-byte
checksum) in the data phase, an invalid frame, and frames
`apple_z2_dispatch_frame()` does not recognise.

## The J71b freeze (fixed)

**Signature.** Touch stops responding. The touch interrupt keeps counting in
`/proc/interrupts`, `/dev/input/event1` delivers nothing, and the kernel log
has no `apple-z2` line. A rebind
(`echo spi0.0 > /sys/bus/spi/drivers/apple-z2/unbind`, then `.../bind`)
brings it back. It happened at the greeter after logout, after a crashed
session, right after a module load, and at random during use.

**Cause.** The controller and the driver were one transfer apart. The data
phase was answered with a **header**, every time the same one:
`e1 56 00 eb 02 00 eb 01 00 eb 01 00 00 00 fc 03` (interrupt data, 86 bytes
pending). The driver took it for a control reply and returned. The level
interrupt fired again, and every later read got the same header back. Since
`REPLY_INTERRUPT_DATA` and `CMD_LAST` are the same byte (`0xe1`), the header
passed the control-reply test.

**Fix.** `kernel/patches/drivers/input/0015`: on J71b, a header in the data
phase is taken as the next frame's header, and the data phase runs again for
it (once per read). On J71b this happens about every ten seconds of use and
around session changes. With the fix, 74 such resyncs over three login rounds
with heavy swiping caused no freeze. The resync logs at debug level.

**Ruled out.** Failed reads (no `runtime packet read failed` line), the frame
tag (a tag resync was tried and never fired), stuck contacts (no lost
releases), evdev close/reopen (the driver has no open/close), and the
compositor (it had the device open, and events flowed again after the fix).

## Other boards

- **J71t (iPad 5)** has its own recovery: on a frame error it releases the
  contacts, masks the interrupt and restarts the controller (`rearm_work`).
  The header-in-data-phase case is not handled there. If a J71t freezes the
  same way, apply the J71b resync to it too.
- **N61 (iPhone 6)** uses the same generation-1 header and data phases with
  its own tag parity. It is not known whether it shows the shift.
- **J172 / D11 / iPhone 7 Plus (generation 2)** read differently (one
  transfer). The resync does not apply. A silent freeze there needs the same
  diagnosis below.

## Diagnosing a freeze on a new board

Capture the state **before** rebinding or reloading anything: both reset the
controller and the evidence with it.

1. **Interrupts and events.** Compare the touch line in `/proc/interrupts`
   over a few seconds while someone swipes, and read the input device as root
   (`timeout 7 cat /dev/input/eventN | wc -c`). Interrupts with no events
   means the driver drops what it reads. No interrupts means the controller
   or its interrupt line.
2. **Who has the device open.** Check `/proc/<compositor pid>/fd` **as root**.
   The greeter runs as another user, so an unprivileged `ls` shows nothing
   and looks like "not open".
3. **Which path drops it.** Add a `dev_warn_ratelimited()` with the first
   bytes of the buffer to each silent return listed above, build only the
   module, and swap it with `rmmod apple_z2; insmod`: no reboot needed, and
   Labwc picks up the new device. Mind the rate limit: a quiet log for more
   than five seconds while the interrupt counts means a path without a log
   line was taken, not that nothing happened.
4. **Reproduce.** Log out and in from SSH (`pkill -u <user> -x labwc` ends
   the session, and the greeter comes back), try the PIN screen, repeat. Log
   kernel lines continuously to a file
   (`journalctl -k -f | grep --line-buffered apple-z2 >> ~/touch-watch.log`)
   so a freeze is captured even when nobody is watching.
