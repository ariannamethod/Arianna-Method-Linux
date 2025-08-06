# Arianna Method Linux Kernel

**Arianna Method Linux Kernel (AMLK)** is a deliberately minimal operating nucleus engineered from Alpine sources to provide a deterministic base for AI workloads.

The kernel is configured to load with a small initramfs derived from Alpine's minirootfs, reducing boot complexity to (O(1)) relative to module count.

OverlayFS support enables layered filesystems, modeled as a union (U = R \cup W) where read-only and writable layers intersect for efficient state changes.

Ext4 remains the default persistent store; its journaling function (J(t)) approximates a bounded integral ensuring data integrity under power loss events.

Namespaces form disjoint sets (N_i) partitioning process views of system resources, allowing safe multitenancy without cross-contamination.

Cgroup hierarchies create a tree (T) with resource limits as edge weights, facilitating precise control over CPU and memory distribution.

Python 3.10+ is included for scriptability, and its virtual environment tool venv allows isolation comparable to constructing subspaces within a vector space.

Node.js 18+ complements Python, providing asynchronous I/O modeled as a non-blocking function (f: E \to E) where events map to themselves after processing.

Bash, curl, and nano compose the minimal interactive toolkit; each utility occupies a vertex in a dependency graph ensuring accessibility without bloat.

The CLI terminal shipped in `letsgo.py` demonstrates logging and echo capabilities, acting as a proof of concept for higher-order reasoning modules.

Logs are stored in /arianna_core/log and each entry is timestamped, forming a sequence ((t_i, m_i)) representing chronological states of dialogue.

The build script uses curl to fetch kernel and rootfs sources, then applies a configuration where required options satisfy predicates for ext4, overlay, and isolation features.

During compilation, the command make -j n leverages parallelism, aligning with the formula for speedup (S = \frac{T_1}{T_n}) from Amdahl's law.

Initramfs assembly employs cpio and gzip, treating the filesystem as a multiset to be serialized into a compressed stream (C) ready for kernel consumption.

The final image concatenates bzImage and the compressed initramfs, yielding a flat artifact optimized for QEMU execution and network deployment.

QEMU invocation sets the console to ttyS0 and disables graphical output, thus the system behaves like a linear state machine observable via standard I/O.

Verifications inside the emulator include python3 --version and node --version; successful output serves as an identity proof for runtime availability.

The project directory conforms to a strict lattice: kernel for build artifacts, core for modules, cmd for executables, usr/bin for runtime tools, and log for reasoning traces.

Each component is annotated with comments using the //: motif, a notation indicating future extensibility in the style of a category morphism awaiting composition.

AMLK is lightweight enough to embed within messaging clients like Telegram, allowing AI agents to inhabit user devices with minimal computational overhead.


## Hardware Requirements

The kernel and userland target generic x86_64 CPUs. GPU drivers and libraries are omitted, so the system runs entirely on CPU hardware.

## Continuous Integration

The CI pipeline builds the kernel and boots it in QEMU using only CPU resources. GPU devices and drivers are absent, and QEMU
is invoked with software acceleration so the workflow succeeds on generic CPU-only runners.

## Building

First build the trimmed package manager:

```
./build/build_apk_tools.sh
```

Then assemble the kernel and userland:

```
./build/build_ariannacore.sh [--with-python] [--clean] [--test-qemu]
```

The second script fetches kernel sources, stages `arianna_core_root` built from the Alpine lineage, and emits a flat image. The optional flags expand the userland, clean previous artifacts or run a QEMU smoke test.

## Linting

Run static analysis before pushing changes (install `flake8`, `flake8-pyproject`, and `black` if missing):

```
./run-tests.sh
```

This script executes `flake8` and `black --check` followed by the test suite. To run the linters directly:

```
flake8 .
black --check .
```

## Lineage utilities

The `apk-tools` directory carries a patched `apk` built by `build_apk_tools.sh`, enabling package installs without heavy dependencies.

## Checksum verification

For reproducibility the build script verifies downloads against known SHA256 sums using:

```
echo "<sha256>  <file>" | sha256sum -c -
```

The current release embeds the following official values:

- `linux-6.6.4.tar.gz`: `43d77b1816942ed010ac5ded8deb8360f0ae9cca3642dc7185898dab31d21396`
- `arianna_core_root-3.19.8-x86_64.tar.gz`: `48230b61c9e22523413e3b90b2287469da1d335a11856e801495a896fd955922`

If a checksum mismatch occurs the build aborts immediately.

## Vendored components

The `apk-tools/` directory carries a pared-down copy of `apk-tools`.
`build/build_apk_tools.sh` compiles this tree and `build/build_ariannacore.sh`
stages the resulting `apk` binary into `arianna_core_root` to install
packages without network access.

Keeping this component local aligns with the CPU-only, minimalistic design:
the build remains self-contained, avoids heavy dependencies and produces a
small userland that boots on generic hardware.

## Running in QEMU

A minimal invocation uses the `arianna-core.img` created during the build. QEMU can operate in headless mode:

```
qemu-system-x86_64 -kernel build/kernel/linux-*/arch/x86/boot/bzImage -initrd build/arianna.initramfs.gz -append "console=ttyS0" -nographic
```

For repeatable experiments, keep memory to 512M and disable reboot so that the exit status bubbles up to the host. The console is directed to `ttyS0`, allowing simple piping to tmux panes or log files.

When `--test-qemu` is supplied to the build script, the above sequence is executed automatically; artifacts remain under the `boot/` directory for manual launches later on.

## Future Interfaces

A Telegram bridge is planned through a small bot that proxies chat messages to `letsgo.py`. The bot will authenticate via API token and map each chat to a session log, enabling asynchronous reasoning threads.

A web UI may follow, exposing the same terminal over WebSockets. The intent is to treat HTTP as a transport layer while preserving the conversational core. SSL termination and rate limiting will rely on existing libraries and can run in user space atop the initramfs.

Other interfaces—serial TTYs, named pipes or custom RPC schemes—remain feasible because the terminal operates in standard I/O space, reducing coupling to any specific frontend.

## letsgo.py

The terminal is invoked after login and serves as the primary shell for Arianna Core. Each session creates a fresh log in `/arianna_core/log/`, stamped with UTC time, ensuring chronological reconstruction of interactions. Configuration is read from `~/.letsgo.toml` (or the path pointed to by `LETSGO_CONFIG`) and can adjust the prompt, theme, color usage, and a `max_log_files` option limiting how many logs are kept on disk. An example file lives at `docs/letsgo.toml.example`.

Command history is persisted to `/arianna_core/log/history`. Existing entries load at startup and are written back on exit. Tab completion, powered by `readline`, suggests built-in verbs like `/status`, `/time`, `/run`, `/summarize`, `/search`, and `/help`.

A `/status` command reports CPU core count, raw uptime seconds read from `/proc/uptime`, and the current host IP. This offers an at-a-glance check that the minimal environment is healthy.

The `/summarize` command searches across logs with optional regular expressions and prints the last five matches; adding `--history` switches the search to the command history. `/search <pattern>` prints every history line matching the given regex.

For quick information retrieval `/time` prints the current UTC timestamp, while `/run <cmd>` executes a shell command and returns its output. A `/help` command lists the available verbs.

By default any unrecognised input is echoed back, but the structure is prepared for more advanced NLP pipelines. Hooks can intercept the text and dispatch it to remote models, feeding results back through the same interface.

Logging uses the `//:` motif in comments and writes both user prompts and letsgo responses. Each line is timestamped with ISO-8601 precision, building a dataset suitable for replay or training.

Because `letsgo.py` resides in the repository root, the `cmd` directory only carries thin launchers. `startup.py` triggers the terminal on boot, while `monitor.sh` tails log files for real-time inspection.

The design keeps dependencies minimal. The script relies only on the Python standard library and can run inside the initramfs without additional packages unless `--with-python` is chosen.

As the project evolves, the terminal is expected to grow into a pluggable orchestrator capable of spawning subprocesses, managing asynchronous tasks and negotiating resources with the kernel via cgroups.

## Architecture

1. **Kernel stratum** – configured through `arianna_kernel.config`, it ensures OverlayFS, ext4, namespaces and cgroups are wired in. Formally the configuration space is a tuple \(K = (k_1, k_2, ..., k_n)\) where each \(k_i\) toggles a capability required for higher layers.
2. **Module layer** – placeholder today, destined to host `.ko` objects. These are morphisms extending \(K\) with elements from the set \(M\), enabling device drivers and specialised subsystems.
3. **Boot image** – the concatenation of `bzImage` and `initramfs` forms a sequence \(B = b \cdot r\), a product in the monoid of binary blobs that QEMU interprets deterministically.
4. **Userland root** – extracted from the Alpine lineage yet renamed to `arianna_core_root`, it is considered the base element \(u_0\) of an overlay lattice where successive changes form \(u_i = u_{i-1} \oplus d_i\).
5. **Command stratum** – the `cmd` directory acts as a set of generators \(C = \{s, m\}\) where `s` launches the terminal and `m` streams logs; additional generators can be added without altering \(B\).
6. **Assistant process** – modelled as a function \(A: I \rightarrow O\) mapping user input to output while appending to a log sequence \(L = [(t_0, i_0), (t_0, o_0), ...]\).
7. **Log space** – each log file defines a time-ordered series, a totally ordered set under the relation "happens-before" derived from timestamps. Summaries operate as projections \(\pi: L \rightarrow L'\).
8. **Interface adapters** – future Telegram or web modules will be functors transforming external message categories into the internal language of the terminal.
9. **Resource governance** – cgroups partition CPU and memory; mathematically they form a tree \(T\) whose edges carry weight limits, and processes are leaves consuming fractions of those weights.
10. **Self-monitoring** – the system aspires to feedback loops where the terminal interprets its own logs, creating a recurrence relation \(x_{n+1} = f(x_n)\) pointing toward reflexive reasoning.


## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
