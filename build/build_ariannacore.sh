#!/usr/bin/env bash
set -euo pipefail

# //: собирает bzImage + initramfs → bootable image

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
KERNEL_VERSION="${KERNEL_VERSION:-6.6.4}"
ACROOT_VERSION="${ACROOT_VERSION:-3.19.0}"
CURL="curl --retry 3 --retry-delay 5 -fL"
SECDB_REPO="${SECDB_REPO:-https://github.com/alpinelinux/alpine-secdb.git}"

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
if [ ! -f "linux-${KERNEL_VERSION}.tar.xz" ]; then
  $CURL -O "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-${KERNEL_VERSION}.tar.xz"  # //: upstream kernel archive
  expected_sha256=$($CURL "https://cdn.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc" | grep " linux-${KERNEL_VERSION}.tar.xz$" | sed -E 's/.*([0-9a-f]{64}).*/\1/')
  echo "${expected_sha256}  linux-${KERNEL_VERSION}.tar.xz" | sha256sum -c - || { echo "SHA256 mismatch for kernel archive" >&2; exit 1; }
  expected_sha512=$($CURL "https://cdn.kernel.org/pub/linux/kernel/v6.x/sha512sums.asc" | grep " linux-${KERNEL_VERSION}.tar.xz$" | sed -E 's/.*([0-9a-f]{128}).*/\1/')
  echo "${expected_sha512}  linux-${KERNEL_VERSION}.tar.xz" | sha512sum -c - || { echo "SHA512 mismatch for kernel archive" >&2; exit 1; }
fi

if [ ! -d "linux-${KERNEL_VERSION}" ]; then
  tar xf "linux-${KERNEL_VERSION}.tar.xz"  # //: unpack kernel tree
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
  $CURL -O "https://dl-cdn.alpinelinux.org/alpine/v${ACROOT_VERSION%.*}/releases/x86_64/alpine-minirootfs-${ACROOT_VERSION}-x86_64.tar.gz"
  $CURL "https://dl-cdn.alpinelinux.org/alpine/v${ACROOT_VERSION%.*}/releases/x86_64/alpine-minirootfs-${ACROOT_VERSION}-x86_64.tar.gz.sha256" | sha256sum -c - || { echo "SHA256 mismatch for acroot archive" >&2; exit 1; }
  $CURL "https://dl-cdn.alpinelinux.org/alpine/v${ACROOT_VERSION%.*}/releases/x86_64/alpine-minirootfs-${ACROOT_VERSION}-x86_64.tar.gz.sha512" | sha512sum -c - || { echo "SHA512 mismatch for acroot archive" >&2; exit 1; }
  mv "alpine-minirootfs-${ACROOT_VERSION}-x86_64.tar.gz" "$TARBALL"
fi
mkdir -p acroot
if [ ! -f acroot/.unpacked ]; then
  tar xf "$TARBALL" -C acroot
  touch acroot/.unpacked
fi

# //: fetch and stage security database
SECDB_DIR="$SCRIPT_DIR/AM-alpine-security-database"
if [ ! -d "$SECDB_DIR" ]; then
  git clone "$SECDB_REPO" "$SECDB_DIR"
fi
mkdir -p acroot/etc/apk
cp -r "$SECDB_DIR"/. acroot/etc/apk/

# //: install runtime packages
PKGS="bash curl nano nodejs npm"
if [ "$WITH_PY" -eq 1 ]; then
  PKGS="$PKGS python3 py3-pip py3-virtualenv"
fi
# shellcheck disable=SC2086
apk --root acroot --repositories-file /etc/apk/repositories --security-db /etc/apk --vuln add --no-cache $PKGS

# //: include assistant, startup hook, motd and log dir
install -Dm755 "$ROOT_DIR/assistant.py" acroot/usr/bin/assistant
install -Dm755 "$ROOT_DIR/cmd/startup.py" acroot/usr/bin/startup
ln -sf /usr/bin/startup acroot/init
mkdir -p acroot/arianna_core/log
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
