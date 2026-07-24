FROM arm32v7/debian:buster

# Buster reached EOL — repos moved to archive.debian.org.
RUN sed -i \
    -e 's|http://deb.debian.org/debian|http://archive.debian.org/debian|g' \
    -e 's|http://security.debian.org|http://archive.debian.org/debian-security|g' \
    -e '/buster-updates/d' \
    /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid

# Install standard apt dependencies that zwoair_imager links against, plus
# gcc to compile the Rockchip stub libraries inside the container, plus
# astrometry.net + sextractor (the plate-solve stack — apt-installed from
# public Debian packages, verified against buster/armhf: see the plan's
# "Findings from the astrometry feasibility spike"). No device-staged
# binaries/libs are needed; apt resolves the full dependency closure.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    make \
    libc6-dev \
    libcfitsio7 \
    libopencv-core3.2 \
    libopencv-imgproc3.2 \
    libopencv-imgcodecs3.2 \
    libopencv-highgui3.2 \
    libopencv-features2d3.2 \
    libopencv-calib3d3.2 \
    libopencv-video3.2 \
    libnova-0.16-0 \
    libxml2 \
    libjpeg62-turbo \
    libssl1.1 \
    libwcs6 \
    libgsl23 \
    libgslcblas0 \
    libavcodec58 \
    libavformat58 \
    libavutil56 \
    libswscale5 \
    libcurl4 \
    libsqlite3-0 \
    sqlite3 \
    libidn2-0 \
    libgomp1 \
    procps \
    psmisc \
    net-tools \
    kmod \
    i2c-tools \
    alsa-utils \
    openssl \
    xxd \
    netcat-openbsd \
    strace \
    python3 \
    python3-numpy \
    python3-astropy \
    file \
    netpbm \
    astrometry.net \
    sextractor \
    && rm -rf /var/lib/apt/lists/*

# sudo: pass-through wrapper (we're already root)
RUN printf '#!/bin/sh\nexec "$@"\n' > /usr/local/bin/sudo && \
    chmod +x /usr/local/bin/sudo

# systemctl: no-op stub — the binary calls "systemctl restart hostapd.service"
# once per minute to manage the WiFi AP. Silently succeed so the popen output
# doesn't pollute the protocol logs.
RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/systemctl && \
    chmod +x /usr/local/bin/systemctl

# lsblk stub: report /dev/mmcblk0p8 mounted at /boot/Image (51 GiB emmc).
# zwoair_imager runs "lsblk -J -n -o NAME,MOUNTPOINT,SIZE" to decide whether
# local storage is "mounted" or "disconnected".
RUN printf '#!/bin/sh\ncase "$*" in\n  *-J*)\n    printf '"'"'{\n   "blockdevices": [\n      {"name":"mmcblk0", "mountpoint":null, "size":"59699M",\n         "children": [\n            {"name":"mmcblk0p8", "mountpoint":"/boot/Image", "size":"59699M"}\n         ]\n      }\n   ]\n}\n'"'"'\n    ;;\n  *) exec /bin/lsblk "$@" 2>/dev/null ;;\nesac\n' \
    > /usr/local/bin/lsblk && chmod +x /usr/local/bin/lsblk

# wpa_cli stub: fake wlan0 connected to "sandbox-net" on 5 GHz.
# The binary (via network.sh) checks "wpa_state=COMPLETED" and "ip_address=..."
# to determine station.server:true in get_device_state.
RUN printf '#!/bin/sh\ncase "$*" in\n  *status*)\n    printf "bssid=aa:bb:cc:dd:ee:ff\nfreq=5805\nssid=sandbox-net\nid=0\nmode=station\npairwise_cipher=CCMP\ngroup_cipher=CCMP\nkey_mgmt=WPA2-PSK\nwpa_state=COMPLETED\nip_address=192.168.1.100\naddress=aa:bb:cc:dd:ee:ff\n"\n    ;;\n  *list_networks*)\n    printf "Network id / ssid / bssid / flags\n0\tsandbox-net\tany\t[CURRENT]\n"\n    ;;\n  *) printf "OK\n" ;;\nesac\n' \
    > /usr/local/bin/wpa_cli && chmod +x /usr/local/bin/wpa_cli

# ifconfig wrapper: pass through to /sbin/ifconfig, but when called with no
# args (interface enumeration) append a fake wlan0.  When called with "wlan0"
# directly (e.g. "ifconfig wlan0 | grep netmask" in network.sh get_state),
# print the interface detail so the netmask line is visible.
RUN printf '#!/bin/sh\nREAL=/sbin/ifconfig\nWLAN_INFO="wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n        inet 192.168.1.100  netmask 255.255.255.0  broadcast 192.168.1.255\n        ether aa:bb:cc:dd:ee:ff  txqueuelen 1000  (Ethernet)"\ncase "$1" in\n  wlan0) printf "%s\n" "$WLAN_INFO" ;;\n  uap0) exit 0 ;;\n  "")\n    $REAL\n    printf "\n%s\n" "$WLAN_INFO"\n    ;;\n  *) $REAL "$@" ;;\nesac\n' \
    > /usr/local/bin/ifconfig && chmod +x /usr/local/bin/ifconfig

# ip wrapper: pass through, but "ip route" appends a fake default gateway on wlan0.
RUN printf '#!/bin/sh\ncase "$*" in\n  *route*)\n    /sbin/ip "$@"\n    printf "default via 192.168.1.1 dev wlan0 metric 302\n"\n    ;;\n  *) exec /sbin/ip "$@" ;;\nesac\n' \
    > /usr/local/bin/ip && chmod +x /usr/local/bin/ip

# iw / iwconfig / wpa_supplicant stubs: network.sh get_state relies on these.
#   iw wlan0 info       → must output "type managed"
#   iwconfig wlan0      → must output "Signal level=-71 dBm"
#   wpa_supplicant      → fake daemon; started with -c <conf> in entrypoint.sh
#                         so is_wpa_run() (ps | grep wpa_supplicant | grep .conf) succeeds.
# /var/log/wpa_supplicant.log must exist so network.sh prints "wpa_run_once".
COPY scripts/ /usr/local/bin/
RUN chmod +x /usr/local/bin/iw /usr/local/bin/iwconfig /usr/local/bin/wpa_supplicant && \
    mkdir -p /var/log && touch /var/log/wpa_supplicant.log

# Build the Rockchip hardware stubs natively inside the armhf container.
COPY stubs/ /opt/stubs/
RUN make -C /opt/stubs

# astrometry.net plate-solve stack: apt-installed above (astrometry.net,
# sextractor packages). The ~350 MB public index files are downloaded by
# emulator/astrometry/download_index.sh and bind-mounted at runtime by
# run.sh — NOT baked into the image. solve-field execs astrometry-engine
# WITHOUT a -c flag, so the engine finds its config by a bindir-relative
# fallback: <bindir>/../etc/astrometry.cfg. With bindir=/usr/bin that
# resolves to /usr/etc/astrometry.cfg (NOT /etc) — so the cfg is symlinked
# there below, and also placed at /etc for tools that read the conventional
# path.
RUN printf 'cpulimit 90\ndepths 10 20 30\nminwidth 0.1\nadd_path /usr/local/astrometry/data\ninparallel\nautoindex\n' \
    > /etc/astrometry.cfg && \
    mkdir -p /usr/etc && ln -sf /etc/astrometry.cfg /usr/etc/astrometry.cfg

# Create the pi user and expected directory tree.
# zwoair_imager looks for config/data under /home/pi/ASIAIR/.
RUN useradd -m -s /bin/bash pi

# WiFi config files expected by network.sh (must come after useradd creates /home/pi).
# wlan0.conf holds key_mgmt/wpa_passphrase (read by ap_state for pi_get_ap);
# wpa_supplicant.conf is the wpa config (same file, see symlink below).
# sh_conf.txt (wpa_svr=1) goes into seed/ so it lands in the .ZWO volume mount.
RUN printf 'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\nupdate_config=1\ncountry=US\nwpa_passphrase=password123\n\nnetwork={\n    ssid="sandbox-net"\n    psk="password123"\n    key_mgmt=WPA2-PSK\n    wpa_key_mgmt=WPA2-PSK\n}\n' \
    > /home/pi/wpa_supplicant.conf && \
    ln -s /home/pi/wpa_supplicant.conf /home/pi/wlan0.conf

# zwoair_imager derives its data dir from HOME — in this container that is
# /root. Create the .ZWO directory and seed an empty userData.db3 so
# SQLite::Database can open it without throwing on first access.
# The real database from a live device can be bind-mounted over this at
# runtime (see run.sh) to get the full object catalog.
RUN mkdir -p /root/.ZWO && \
    sqlite3 /root/.ZWO/userData.db3 "VACUUM;" && \
    mkdir -p /tmp/zwo/log

WORKDIR /home/pi/ASIAIR

# entrypoint.sh detects the runtime SN and writes a synthetic zwoair_license
# before the binary's first periodic license check fires (~9 s after start).
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# LD_LIBRARY_PATH search order:
#   1. /opt/stubs   — Rockchip hardware stubs
#   2. /home/pi/ASIAIR/lib  — libyuv, libonnxruntime, libzhistogram
ENV LD_LIBRARY_PATH=/opt/stubs:/home/pi/ASIAIR/lib

# Intercept open("/proc/device-tree/model") and return the expected board
# identity string so hardware detection doesn't abort at startup.
ENV LD_PRELOAD=/opt/stubs/libhwid.so

# Prevent OpenMP/BLAS/ONNX background threads from initializing SIMD routines
# that QEMU can't emulate, which causes a SIGILL ~60s after startup and hangs
# the binary's TCP request-processing thread.
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV ORT_DISABLE_ALL=1

# TCP 4700/4701 — zwoair_imager main JSON-RPC control + secondary listener
# TCP 4800/4801 — zwoair_imager imaging / RTSP + secondary listener
# TCP 80        — zwoair_file_server (spawned by imager)
# UDP 4720      — zwoair_imager UDP channel
EXPOSE 4700 4701 4800 4801 80
EXPOSE 4720/udp

CMD ["/usr/local/bin/entrypoint.sh"]
