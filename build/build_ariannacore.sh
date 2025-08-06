#!/usr/bin/env bash
set -euo pipefail

# //: собирает bzImage + initramfs → bootable image

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
KERNEL_VERSION="${KERNEL_VERSION:-6.6.4}"
KERNEL_SHA256="${KERNEL_SHA256:-43d77b1816942ed010ac5ded8deb8360f0ae9cca3642dc7185898dab31d21396}"
ACROOT_VERSION="${ACROOT_VERSION:-3.19.8}"
ACROOT_SHA256="${ACROOT_SHA256:-48230b61c9e22523413e3b90b2287469da1d335a11856e801495a896fd955922}"
CURL="curl --retry 3 --retry-delay 5 -fL"
LOG_DIR="/arianna_core/log"

WITH_PY=0
CLEAN=0
TEST_QEMU=0
for arg in "$@"; do
  case "$arg" in
    --with-python) WITH_PY=1 ;;
    --clean) CLEAN=1 ;;
    --test-qemu) TEST_QEMU=1 ;;
  esac
done

if [ "$CLEAN" -eq 1 ]; then
  rm -rf "$SCRIPT_DIR/kernel" "$SCRIPT_DIR/acroot" "$SCRIPT_DIR/arianna.initramfs.gz" "$SCRIPT_DIR/arianna-core.img"
fi

# //: fetch kernel sources
mkdir -p "$SCRIPT_DIR/kernel"
cd "$SCRIPT_DIR/kernel"
if [ ! -f "linux-${KERNEL_VERSION}.tar.gz" ]; then
  $CURL -o "linux-${KERNEL_VERSION}.tar.gz" "https://github.com/gregkh/linux/archive/refs/tags/v${KERNEL_VERSION}.tar.gz"  # //: upstream kernel archive
  echo "${KERNEL_SHA256}  linux-${KERNEL_VERSION}.tar.gz" | sha256sum -c - || { echo "SHA256 mismatch for kernel archive" >&2; exit 1; }
fi

if [ ! -d "linux-${KERNEL_VERSION}" ]; then
  tar xf "linux-${KERNEL_VERSION}.tar.gz"  # //: unpack kernel tree
fi

cd "linux-${KERNEL_VERSION}"

# //: kernel configuration
if [ ! -f .config ]; then
  cp "$SCRIPT_DIR/arianna_kernel.config" .config  # //: baseline config with ext4, overlayfs, cgroups, namespaces
fi

# //: interactive customization when needed
# make menuconfig  # //: enable extra modules as project evolves

# //: build kernel and modules
make -j"$(nproc)" bzImage modules
make modules_install INSTALL_MOD_PATH="$SCRIPT_DIR/acroot"  # //: install to initramfs staging

# //: assemble initramfs with arianna_core_root built from the Alpine lineage
cd "$SCRIPT_DIR"
TARBALL="arianna_core_root-${ACROOT_VERSION}-x86_64.tar.gz"
if [ ! -f "$TARBALL" ]; then
  $CURL -o "$TARBALL" "https://raw.githubusercontent.com/alpinelinux/docker-alpine/f2420d7551c86c2cd3fab04159b57b9bcc533647/x86_64/alpine-minirootfs-${ACROOT_VERSION}-x86_64.tar.gz"
  echo "${ACROOT_SHA256}  $TARBALL" | sha256sum -c - || { echo "SHA256 mismatch for acroot archive" >&2; exit 1; }
fi
mkdir -p acroot
if [ ! -f acroot/.unpacked ]; then
  tar xf "$TARBALL" -C acroot
  touch acroot/.unpacked
fi

# //: build and install Alpine configuration utilities (CPU-only)
make -C "$ROOT_DIR/for-codex-alpine-conf"
make -C "$ROOT_DIR/for-codex-alpine-conf" install PREFIX=/usr DESTDIR="$SCRIPT_DIR/acroot"
rm -f \
  acroot/usr/sbin/setup-desktop \
  acroot/usr/sbin/setup-wayland-base \
  acroot/usr/sbin/setup-xorg-base

# //: build and stage patched apk-tools
APK_BIN="$("$SCRIPT_DIR/build_apk_tools.sh")"
install -Dm755 "$APK_BIN" acroot/usr/bin/apk

# //: install runtime packages using the patched apk
PKGS="bash curl nano nodejs npm"
if [ "$WITH_PY" -eq 1 ]; then
  PKGS="$PKGS python3 py3-pip py3-virtualenv"
fi
# shellcheck disable=SC2086
"$APK_BIN" --root acroot --repositories-file /etc/apk/repositories add --no-cache $PKGS

# //: include assistant, startup hook, motd and log dir
install -Dm755 "$ROOT_DIR/assistant.py" acroot/usr/bin/assistant
install -Dm755 "$ROOT_DIR/cmd/startup.py" acroot/usr/bin/startup
ln -sf /usr/bin/startup acroot/init
mkdir -p "acroot${LOG_DIR}"
echo "Hey there, welcome to Arianna Method Linux Terminal" > acroot/etc/motd

# //: create initramfs image
cd acroot
find . | cpio -o -H newc | gzip -9 > "$SCRIPT_DIR/arianna.initramfs.gz"
cd "$SCRIPT_DIR"

# //: build final disk image
cat "kernel/linux-${KERNEL_VERSION}/arch/x86/boot/bzImage" "arianna.initramfs.gz" > "$SCRIPT_DIR/arianna-core.img"  # //: flat image for qemu

if [ "$TEST_QEMU" -eq 1 ]; then
  qemu-system-x86_64 \
    -kernel "kernel/linux-${KERNEL_VERSION}/arch/x86/boot/bzImage" \
    -initrd "arianna.initramfs.gz" \
    -append "console=ttyS0" \
    -nographic \
    -no-reboot \
    -serial mon:stdio \
    -m 512M
fi

# //: verify language runtimes inside the VM (executed via expect or manual)
# python3 --version  # //: confirm Python 3.10+
# node --version     # //: confirm Node.js 18+
