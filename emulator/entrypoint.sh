#!/bin/bash
# Wrapper for zwoair_imager that generates a valid zwoair_license before startup.
#
# The license SN is derived from /proc/cpuinfo Serial: XOR of the upper and
# lower 32-bit halves of the 64-bit serial.  On the real device the serial is
# the Rockchip CPU unique ID; in the container it is the fixed value set in
# stub_hwid.c (CPUINFO_SERIAL).
#
# Formula verified against a real device:
#   Serial cf6e09e382b50cd6 → cf6e09e3 XOR 82b50cd6 = 4ddb0535 (matches live license)
#
# Because this script and the binary's verifyPlus both derive sn/digest from
# the same serial with the same formula, the generated license is always
# self-consistent — pi_is_verified passes for ANY CPUINFO_SERIAL value, not
# just one matching a real device.

AUTH_CODE="cd32cd7f1798464ba4c3f17fea85040e"
# sign field is not locally verified; keep original to have a well-formed file.
SIGN="c1fDIZFCv0qkJchn72C3yk5IT/sVJfy+rayLR7MCr1Xv6P+NuIgFGqRt/vGOqe9ekbxspWZy8XEK05qkTVWoxUzS5xKEMVOfbJrHstf8IooUHXs5FDSyXahovOrKEvH4LwTvh2be3wPr4VuMuQ9/Ci71ZtZ9z5OZq0CUNG7gZoU="
LICENSE_PATH="/home/pi/.ZWO/zwoair_license"
IMAGER="/home/pi/ASIAIR/bin/zwoair_imager"

# Read CPU serial from /proc/cpuinfo (intercepted by LD_PRELOAD stub).
CPU_SERIAL=$(grep 'Serial' /proc/cpuinfo | awk '{print $NF}')
if [ -z "$CPU_SERIAL" ]; then
    echo "[entrypoint] WARNING: could not read CPU serial, defaulting to 0000000000000000"
    CPU_SERIAL="0000000000000000"
fi

# XOR upper and lower 32-bit halves to produce the 8-char hex license SN.
UPPER=$(printf '%d' "0x${CPU_SERIAL:0:8}")
LOWER=$(printf '%d' "0x${CPU_SERIAL:8:8}")
SN=$(printf '%08x' $(( UPPER ^ LOWER )))

# Compute HMAC-SHA256 digest: HMAC("zwo.asiair", sn || auth_code) → binary → base64
DIGEST=$(printf '%s' "${SN}${AUTH_CODE}" | \
    openssl dgst -sha256 -hmac "zwo.asiair" -binary | openssl base64)

printf '{"sn":"%s","auth_code":"%s","digest":"%s","sign":"%s"}' \
    "$SN" "$AUTH_CODE" "$DIGEST" "$SIGN" > "$LICENSE_PATH"

echo "[entrypoint] CPU serial: ${CPU_SERIAL}"
echo "[entrypoint] license sn: ${SN}  digest: ${DIGEST}"

# Fake wpa_supplicant process so network.sh is_wpa_run() sees it in ps.
# Must be started with a .conf argument so "grep .conf" in is_wpa_run matches.
/usr/local/bin/wpa_supplicant -c /home/pi/wpa_supplicant.conf &
WPA_PID=$!

# Start the mount controller stub so scope commands don't return code:103.
/opt/stubs/mount_stub &
MOUNT_PID=$!

# Run the imager as a child (not exec) so this script can supervise shutdown.
# Ctrl-C (SIGINT) / docker stop (SIGTERM) are forwarded to the binary so its
# own graceful teardown runs; if it wedges, force-kill after a grace period so
# the container always exits and the --rm cleanup fires.
"$IMAGER" &
IMAGER_PID=$!

shutdown() {
    echo "[entrypoint] caught signal — forwarding SIGINT to imager (pid ${IMAGER_PID})"
    kill -INT "$IMAGER_PID" 2>/dev/null || true
    # Wait up to ~10s for graceful exit, then force-kill.
    for _ in $(seq 1 40); do
        kill -0 "$IMAGER_PID" 2>/dev/null || break
        sleep 0.25
    done
    if kill -0 "$IMAGER_PID" 2>/dev/null; then
        echo "[entrypoint] imager did not exit — SIGKILL"
        kill -KILL "$IMAGER_PID" 2>/dev/null || true
    fi
    kill "$WPA_PID" "$MOUNT_PID" 2>/dev/null || true
    exit 0
}
trap shutdown INT TERM

wait "$IMAGER_PID"
EXIT_CODE=$?
echo "[entrypoint] imager exited (code ${EXIT_CODE}) — stopping stubs"
kill "$WPA_PID" "$MOUNT_PID" 2>/dev/null || true
exit "$EXIT_CODE"
