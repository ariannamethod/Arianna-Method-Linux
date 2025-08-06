# Arianna Method Linux Kernel

[![CI](https://github.com/OWNER/Arianna-Linux-Kernel/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/Arianna-Linux-Kernel/actions/workflows/ci.yml)

🔹 This is not just a Linux kernel. Arianna Core is a compact AI-first kernel framework.

## Continuous Integration

The CI pipeline builds the kernel and boots it in QEMU using only CPU resources. GPU devices and drivers are absent, and QEMU
is invoked with software acceleration so the workflow succeeds on generic CPU-only runners.

## Building

The project ships a single entry script, `./build/build_ariannacore.sh`, which acquires kernel sources, prepares an `arianna_core_root` userland and emits a flat image. Run it from a fresh checkout to obtain a `bzImage` coupled with an `initramfs` that is aware of the assistant and the motd.

The base image only brings in a minimal toolset (`bash`, `curl` and `nano`). Passing `--with-python` expands the userland with the CPython runtime and tooling, while `--with-node` pulls in the heavier Node.js and npm toolchain for JavaScript workflows. The `--clean` flag wipes previous artifacts, and `--test-qemu` executes a minimal boot in QEMU to validate that the emission succeeded.

## Checksum verification

For reproducibility the build script verifies downloads against known SHA256 sums using:

```
echo "<sha256>  <file>" | sha256sum -c -
```

The current release embeds the following official values:

- `linux-6.6.4.tar.gz`: `43d77b1816942ed010ac5ded8deb8360f0ae9cca3642dc7185898dab31d21396`
- `alpine-minirootfs-3.19.8-x86_64.tar.gz`: `48230b61c9e22523413e3b90b2287469da1d335a11856e801495a896fd955922`

If a checksum mismatch occurs the build aborts immediately.

## Running in QEMU

A minimal invocation uses the `arianna-core.img` created during the build. QEMU can operate in headless mode:

```
qemu-system-x86_64 -kernel build/kernel/linux-*/arch/x86/boot/bzImage -initrd build/arianna.initramfs.gz -append "console=ttyS0" -nographic
```

For repeatable experiments, keep memory to 512M and disable reboot so that the exit status bubbles up to the host. The console is directed to `ttyS0`, allowing simple piping to tmux panes or log files.

When `--test-qemu` is supplied to the build script, the above sequence is executed automatically; artifacts remain under the `boot/` directory for manual launches later on.

## Future Interfaces

A Telegram bridge is planned through a small bot that proxies chat messages to `assistant.py`. The bot will authenticate via API token and map each chat to a session log, enabling asynchronous reasoning threads.

A web UI may follow, exposing the same assistant over WebSockets. The intent is to treat HTTP as a transport layer while preserving the conversational core. SSL termination and rate limiting will rely on existing libraries and can run in user space atop the initramfs.

Other interfaces—serial TTYs, named pipes or custom RPC schemes—remain feasible because the assistant operates in standard I/O space, reducing coupling to any specific frontend.

## assistant.py

The assistant is invoked after login and serves as the primary shell for Arianna Core. Each session creates a fresh log in `/arianna_core/log/`, stamped with UTC time, ensuring chronological reconstruction of interactions.

A `/status` command reports CPU core count, raw uptime seconds read from `/proc/uptime`, and the current host IP. This offers an at-a-glance check that the minimal environment is healthy.

The `/summarize` command performs a naive search across all session logs and prints the last five matches, demonstrating how higher-order reasoning can be layered atop simple text filters.

By default any unrecognised input is echoed back, but the structure is prepared for more advanced NLP pipelines. Hooks can intercept the text and dispatch it to remote models, feeding results back through the same interface.

Logging uses the `//:` motif in comments and writes both user prompts and assistant responses. Each line is timestamped with ISO-8601 precision, building a dataset suitable for replay or training.

Because the assistant resides in the repository root, the `cmd` directory only carries thin launchers. `startup.py` triggers the assistant on boot, while `monitor.sh` tails log files for real-time inspection.

The design keeps dependencies minimal. The script relies only on the Python standard library and can run inside the initramfs without additional packages unless `--with-python` is chosen.

As the project evolves, the assistant is expected to grow into a pluggable orchestrator capable of spawning subprocesses, managing asynchronous tasks and negotiating resources with the kernel via cgroups.

## Architecture

1. **Kernel stratum** – configured through `arianna_kernel.config`, it ensures OverlayFS, ext4, namespaces and cgroups are wired in. Formally the configuration space is a tuple \(K = (k_1, k_2, ..., k_n)\) where each \(k_i\) toggles a capability required for higher layers.
2. **Module layer** – placeholder today, destined to host `.ko` objects. These are morphisms extending \(K\) with elements from the set \(M\), enabling device drivers and specialised subsystems.
3. **Boot image** – the concatenation of `bzImage` and `initramfs` forms a sequence \(B = b \cdot r\), a product in the monoid of binary blobs that QEMU interprets deterministically.
4. **Userland root** – extracted from the Alpine lineage yet renamed to `arianna_core_root`, it is considered the base element \(u_0\) of an overlay lattice where successive changes form \(u_i = u_{i-1} \oplus d_i\).
5. **Command stratum** – the `cmd` directory acts as a set of generators \(C = \{s, m\}\) where `s` launches the assistant and `m` streams logs; additional generators can be added without altering \(B\).
6. **Assistant process** – modelled as a function \(A: I \rightarrow O\) mapping user input to output while appending to a log sequence \(L = [(t_0, i_0), (t_0, o_0), ...]\).
7. **Log space** – each log file defines a time-ordered series, a totally ordered set under the relation "happens-before" derived from timestamps. Summaries operate as projections \(\pi: L \rightarrow L'\).
8. **Interface adapters** – future Telegram or web modules will be functors transforming external message categories into the internal language of the assistant.
9. **Resource governance** – cgroups partition CPU and memory; mathematically they form a tree \(T\) whose edges carry weight limits, and processes are leaves consuming fractions of those weights.
10. **Self-monitoring** – the system aspires to feedback loops where the assistant interprets its own logs, creating a recurrence relation \(x_{n+1} = f(x_n)\) pointing toward reflexive reasoning.


## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
