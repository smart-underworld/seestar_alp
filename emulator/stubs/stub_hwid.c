/*
 * LD_PRELOAD stub: intercepts open/fopen for /proc/device-tree/model
 * and returns a memfd containing the expected board identity string.
 *
 * zwoair_imager reads this path 11+ times (from multiple threads) to
 * identify the hardware. Without it the binary crashes with SIGABRT
 * shortly after launch.
 *
 * Compile: gcc -shared -fPIC -ldl -o libhwid.so stub_hwid.c
 * Use:     LD_PRELOAD=/opt/stubs/libhwid.so zwoair_imager
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <dirent.h>
#include <errno.h>
#include <sys/mman.h>
#include <time.h>
#include <poll.h>
#include <sys/select.h>
#include <signal.h>
#include <execinfo.h>
#include <ucontext.h>

/* ---------------------------------------------------------------------------
 * Crash diagnostics.  The binary installs its own SIGSEGV handler that merely
 * logs "[handler]caught signal 11" and re-raises → core dump with no location.
 * We install our own SA_SIGINFO handler *and* intercept sigaction()/signal()
 * so the binary can't shadow it for SIGSEGV/SIGBUS.  On a fault we print the
 * fault address, the faulting PC and LR (ARM32 ucontext), and a backtrace.
 * The binary is non-PIE (link base 0x10000), so a PC in the main image maps
 * directly to a VA — subtract nothing, look it up in the disassembly.
 * Set SEESTAR_NO_CRASH_TRAP=1 to disable (fall back to the binary's handler). */
static int (*real_sigaction)(int, const struct sigaction *, struct sigaction *) = NULL;
/* The imager popen()s many short-lived helpers (grep/ps/i2cget/network.sh) that
 * inherit LD_PRELOAD.  Only arm the crash trap in the imager itself, so we don't
 * touch those children's signal handling or spam their startup into the log. */
static int is_imager_process(void) {
    static int cached = -1;
    if (cached != -1) return cached;
    char exe[512];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof(exe) - 1);
    cached = 0;
    if (n > 0) {
        exe[n] = '\0';
        if (strstr(exe, "zwoair_imager")) cached = 1;
    }
    return cached;
}
static void crash_hex(char *out, unsigned long v) {
    static const char hx[] = "0123456789abcdef";
    out[0] = '0'; out[1] = 'x';
    for (int i = 0; i < 8; i++) out[2 + i] = hx[(v >> ((7 - i) * 4)) & 0xf];
    out[10] = '\0';
}
static void crash_line(const char *label, unsigned long v) {
    char h[11]; crash_hex(h, v);
    write(2, label, strlen(label));
    write(2, h, 10);
    write(2, "\n", 1);
}
static void crash_symbolize(const char *label, unsigned long addr) {
    Dl_info info;
    write(2, label, strlen(label));
    if (dladdr((void *)addr, &info) && info.dli_fname) {
        write(2, info.dli_fname, strlen(info.dli_fname));
        if (info.dli_sname) {
            char h[11];
            unsigned long off = addr - (unsigned long)info.dli_saddr;
            write(2, "(", 1);
            write(2, info.dli_sname, strlen(info.dli_sname));
            write(2, "+", 1);
            crash_hex(h, off);
            write(2, h, 10);
            write(2, ")", 1);
        }
        write(2, "\n", 1);
    } else {
        write(2, "?\n", 2);
    }
}
static void crash_handler(int sig, siginfo_t *si, void *uctx) {
    write(2, "\n=== [hwid_stub] CRASH TRAP ===\n", 31);
    crash_line("signal      = ", (unsigned long)sig);
    crash_line("fault addr  = ", (unsigned long)(si ? si->si_addr : 0));
#if defined(__arm__)
    if (uctx) {
        ucontext_t *uc = (ucontext_t *)uctx;
        crash_line("pc          = ", (unsigned long)uc->uc_mcontext.arm_pc);
        crash_line("lr          = ", (unsigned long)uc->uc_mcontext.arm_lr);
        crash_line("sp          = ", (unsigned long)uc->uc_mcontext.arm_sp);
        crash_line("r0          = ", (unsigned long)uc->uc_mcontext.arm_r0);
        crash_line("r1          = ", (unsigned long)uc->uc_mcontext.arm_r1);
        crash_symbolize("pc sym      = ", (unsigned long)uc->uc_mcontext.arm_pc);
        crash_symbolize("lr sym      = ", (unsigned long)uc->uc_mcontext.arm_lr);
    }
#endif
    void *bt[32];
    int n = backtrace(bt, 32);
    write(2, "backtrace:\n", 11);
    backtrace_symbols_fd(bt, n, 2);
    write(2, "=== end crash trap ===\n", 23);
    /* Re-raise with the default disposition so a core is still produced.
     * Use the pre-resolved real sigaction (async-signal-safe: no dlsym here). */
    if (real_sigaction) {
        struct sigaction dfl;
        memset(&dfl, 0, sizeof(dfl));
        dfl.sa_handler = SIG_DFL;
        real_sigaction(sig, &dfl, NULL);
    }
    raise(sig);
}
static void install_crash_trap(void) {
    if (getenv("SEESTAR_NO_CRASH_TRAP")) return;
    if (!is_imager_process()) return;
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO;
    sigemptyset(&sa.sa_mask);
    if (!real_sigaction) real_sigaction = dlsym(RTLD_NEXT, "sigaction");
    real_sigaction(SIGSEGV, &sa, NULL);
    real_sigaction(SIGBUS,  &sa, NULL);
    real_sigaction(SIGABRT, &sa, NULL);
}
static int crash_trap_owns(int signum) {
    return !getenv("SEESTAR_NO_CRASH_TRAP") && is_imager_process() &&
           (signum == SIGSEGV || signum == SIGBUS || signum == SIGABRT);
}
/* Intercept sigaction(): let the binary set handlers for everything except the
 * signals we've claimed for crash diagnostics — for those, pretend success but
 * keep our handler installed. */
int sigaction(int signum, const struct sigaction *act, struct sigaction *old) {
    if (!real_sigaction) real_sigaction = dlsym(RTLD_NEXT, "sigaction");
    if (act && crash_trap_owns(signum)) {
        fprintf(stderr, "[hwid_stub] blocked binary sigaction(%d) — keeping crash trap\n", signum);
        fflush(stderr);
        if (old) real_sigaction(signum, NULL, old);
        return 0;
    }
    return real_sigaction(signum, act, old);
}
typedef void (*sighandler_t)(int);
sighandler_t signal(int signum, sighandler_t handler) {
    static sighandler_t (*real)(int, sighandler_t) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "signal");
    if (crash_trap_owns(signum) && handler != SIG_DFL) {
        fprintf(stderr, "[hwid_stub] blocked binary signal(%d) — keeping crash trap\n", signum);
        fflush(stderr);
        return NULL;
    }
    return real(signum, handler);
}
__attribute__((constructor))
static void hwid_stub_init(void) {
    install_crash_trap();
}

/* Per-frame camera chatter (raw ioctl dispatch, QBUF/DQBUF, poll/ppoll/select)
 * fires 30x/sec and drowns out everything else in the log.  Gate it behind
 * SEESTAR_CAM_VERBOSE=1; state-transition logs (format negotiation, REQBUFS,
 * STREAMON/OFF, EFW moves, wheel/autofocus events) stay on unconditionally. */
static int cam_verbose(void) {
    static int v = -1;
    if (v == -1) v = getenv("SEESTAR_CAM_VERBOSE") ? 1 : 0;
    return v;
}

#define MODEL_PATH   "/proc/device-tree/model"
#define MODEL_STR_DEFAULT "ZWO SeeStar Board V0.1 (Rockchip-RV1126-Linux)"

/* zwoair_imager is one shared binary across the whole SeeStar lineup; it
 * picks its model-specific code paths (focuser dispatch, ISP tuning dir,
 * camera detection, etc.) by matching this string. Exact match substrings
 * confirmed via `strings` on the binary itself (zwoair_imager_spec research,
 * 2026-06-24) — these are the literal compared values, not guesses:
 *   "ZWO SeeStar Board", "ZWO SeeStar S50v2 Board", "ZWO SeeStar S50P Board",
 *   "ZWO SeeStar S30 Board", "ZWO SeeStar S30P Board"
 * SEESTAR_MODEL selects one at container start; default matches the real
 * S50 device's full /proc/device-tree/model string (with version/SoC
 * suffix) seen over SSH. The other models' suffixes aren't verified against
 * real hardware, but the binary's own S50 match ignores that suffix, so a
 * bare model string is sufficient for the rest. */
static const char *model_str(void) {
    const char *m = getenv("SEESTAR_MODEL");
    if (!m || !*m) return MODEL_STR_DEFAULT;
    if (strcmp(m, "S50") == 0)   return MODEL_STR_DEFAULT;
    if (strcmp(m, "S50V2") == 0) return "ZWO SeeStar S50v2 Board";
    if (strcmp(m, "S50P") == 0)  return "ZWO SeeStar S50P Board";
    if (strcmp(m, "S30") == 0)   return "ZWO SeeStar S30 Board";
    if (strcmp(m, "S30P") == 0)  return "ZWO SeeStar S30P Board";
    return MODEL_STR_DEFAULT;
}

#define THERMAL_PATH "/sys/class/thermal/thermal_zone0/temp"
#define THERMAL_STR  "45000\n"   /* 45 °C in millidegrees */

#define CHARGER_PATH  "/sys/class/power_supply/bq25890-charger/status"
#define CHARGER_STR   "Not charging\n"

#define BATTERY_PATH   "/sys/class/power_supply/battery/capacity"
#define BATTERY_STR    "100\n"

#define CHARGER_ONLINE_PATH "/sys/class/power_supply/bq25890-charger/online"
#define CHARGER_ONLINE_STR  "1\n"

#define CHARGER_TEMP_PATH   "/sys/class/power_supply/bq25890-charger/temp"
#define CHARGER_TEMP_STR    "25\n"   /* whole degrees C */

#define BATT_VOLTAGE_PATH   "/sys/class/power_supply/battery/voltage_now"
#define BATT_VOLTAGE_STR    "4000000\n"  /* microvolts: 4.0 V */

#define BATT_CURRENT_PATH   "/sys/class/power_supply/battery/current_now"
#define BATT_CURRENT_STR    "0\n"        /* microamps: not charging */

/* /proc/cpuinfo: firmware reads the Serial field to validate zwoair_license.
 * entrypoint.sh derives the license sn/digest from whatever serial is set
 * here, using the same formula the binary uses to verify it — so the
 * license is self-consistent and pi_is_verified passes regardless of this
 * value. No real device serial or license file is needed. */
#define CPUINFO_PATH    "/proc/cpuinfo"
#define CPUINFO_SERIAL  "0000000000000000"
#define CPUINFO_STR     "Hardware\t: Generic DT based system\nRevision\t: 0000\nSerial\t\t: " CPUINFO_SERIAL "\n"

/* /proc/net/wireless: binary reads signal level for get_device_state station.sig_lev */
#define WIRELESS_PATH   "/proc/net/wireless"
#define WIRELESS_STR    "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n" \
                        " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n" \
                        " wlan0: 0000   70.  -71.  -256.       0      0      0      0      0        0\n"

/* /dev/eaf-misc: GPIO-driven focuser misc device. Real driver isn't present
 * in the container; redirect the open() to /dev/null so eaf_open() at least
 * gets a valid fd to probe with ioctl, instead of failing outright at open(). */
#define EAF_MISC_PATH   "/dev/eaf-misc"
/* The electronic filter wheel (EFW: dark/IRCUT/LP) is driven through this GPIO/PWM
 * misc device — verified on a real S50: the imager holds it open (fd) and moves
 * the wheel via two custom ioctls (type 'C'), returning 0. Absent in the
 * container, so open+ioctl fail → WheelMove "set efw pos failed" (code 508).
 * Redirect the open to /dev/null and fake the ioctls (see ioctl()). */
#define PWM_MISC_PATH   "/dev/pwm-gpio-misc"

static int make_string_fd(const char *s, int len) {
    int pfd[2];
    if (pipe(pfd) < 0) return -1;
    write(pfd[1], s, len);
    close(pfd[1]);
    return pfd[0];
}

static int make_model_fd(void) {
    const char *s = model_str();
    return make_string_fd(s, strlen(s));
}
#define make_thermal_fd() make_string_fd(THERMAL_STR, sizeof(THERMAL_STR) - 1)
#define make_charger_fd() make_string_fd(CHARGER_STR, sizeof(CHARGER_STR) - 1)

static int fd_for_path(const char *path) {
    if (strcmp(path, MODEL_PATH)   == 0) return make_model_fd();
    if (strcmp(path, THERMAL_PATH) == 0) return make_thermal_fd();
    if (strcmp(path, CHARGER_PATH) == 0) return make_charger_fd();
    if (strcmp(path, BATTERY_PATH)        == 0) return make_string_fd(BATTERY_STR,        sizeof(BATTERY_STR)        - 1);
    if (strcmp(path, CHARGER_ONLINE_PATH) == 0) return make_string_fd(CHARGER_ONLINE_STR, sizeof(CHARGER_ONLINE_STR) - 1);
    if (strcmp(path, CHARGER_TEMP_PATH)   == 0) return make_string_fd(CHARGER_TEMP_STR,   sizeof(CHARGER_TEMP_STR)   - 1);
    if (strcmp(path, BATT_VOLTAGE_PATH)   == 0) return make_string_fd(BATT_VOLTAGE_STR,   sizeof(BATT_VOLTAGE_STR)   - 1);
    if (strcmp(path, BATT_CURRENT_PATH)   == 0) return make_string_fd(BATT_CURRENT_STR,   sizeof(BATT_CURRENT_STR)   - 1);
    if (strcmp(path, CPUINFO_PATH)  == 0) return make_string_fd(CPUINFO_STR,   sizeof(CPUINFO_STR)   - 1);
    if (strcmp(path, WIRELESS_PATH) == 0) return make_string_fd(WIRELESS_STR, sizeof(WIRELESS_STR) - 1);
    return -2; /* sentinel: not intercepted */
}

/* fd most recently opened for EAF_MISC_PATH, so ioctl() can log/handle it
 * without spamming logs for ioctls on unrelated fds (sockets, etc). */
static int eaf_fd = -1;

/* EFW (filter wheel) on /dev/pwm-gpio-misc. Real-device ioctls (strace):
 *   GET = _IOC(READ,  'C'=0x43, 1, 8)  = 0x80084301  (read current 8-byte state)
 *   SET = _IOC(WRITE, 'C'=0x43, 7, 8)  = 0x40084307  (write target 8-byte state)
 * polled in a read/write loop until arrival. We echo the last SET payload back on
 * GET so the imager sees "commanded == current" and the move completes. */
#define EFW_GET 0x80084301U
#define EFW_SET 0x40084307U
static int     pwm_fd = -1;
static uint8_t efw_state[8] = {0};  /* last commanded EFW state, echoed on GET */

/* Streaming state — set by VIDIOC_STREAMON, cleared by STREAMOFF.
 * Used by select() intercept to know when to inject frame-ready signals. */
static volatile int _streaming = 0;
static volatile int _frame_fd  = -1;

/* Camera device fds: track video/media/v4l-subdev fds opened for fake camera.
 * All V4L2 ioctls on these fds are faked to return 0 so the binary's ASICAM
 * layer can proceed past device-open checks. */
/* Track camera fds with per-fd type so DQBUF/S_FMT return the right sizes.
 * The binary distinguishes: /dev/video0 (RAW10 Bayer) vs /dev/video4 (NV12
 * YUV420 from ISP). ASICAM_GetImage has separate code paths for each and
 * validates bytesused against format-specific stride formulas:
 *   RAW10: ((width*10/8 + 255)>>8)*256 * height = 2,764,800
 *   NV12:  ((width*3/2  + 255)>>8)*256 * height = 3,317,760  */
typedef enum { CAM_FD_TYPE_GENERIC = 0, CAM_FD_TYPE_RAW = 1, CAM_FD_TYPE_YUV = 2 } cam_fd_type_t;
#define MAX_CAM_FDS 16
static int          cam_fds[MAX_CAM_FDS];
static cam_fd_type_t cam_fd_types[MAX_CAM_FDS];
static int cam_fd_count = 0;

static void cam_fd_add(int fd, cam_fd_type_t type) {
    if (cam_fd_count < MAX_CAM_FDS) {
        cam_fds[cam_fd_count]      = fd;
        cam_fd_types[cam_fd_count] = type;
        cam_fd_count++;
    }
}
static int cam_fd_is_tracked(int fd) {
    for (int i = 0; i < cam_fd_count; i++) if (cam_fds[i] == fd) return 1;
    return 0;
}
static cam_fd_type_t cam_fd_get_type(int fd) {
    for (int i = 0; i < cam_fd_count; i++) if (cam_fds[i] == fd) return cam_fd_types[i];
    return CAM_FD_TYPE_GENERIC;
}

/* Sensor name for ASICAM_Scan fake popen output, keyed to SEESTAR_MODEL.
 * Derived from iqfiles: S50→imx462, S50N→imx662, S50P→imx585, S30→imx662,
 * S30P→imx585. SEESTAR_MODEL is resolved by model_str() to a board string;
 * we just need to pick the right sensor per variant. */
static const char *camera_sensor_name(void) {
    const char *m = getenv("SEESTAR_MODEL");
    if (!m || !*m || strcmp(m, "S50") == 0) return "imx462";
    if (strcmp(m, "S50V2") == 0) return "imx662";  /* S50v2 uses S50N iqfiles → imx662 */
    if (strcmp(m, "S50P") == 0)  return "imx585";
    if (strcmp(m, "S30") == 0)   return "imx662";
    if (strcmp(m, "S30P") == 0)  return "imx585";
    return "imx462";
}

static void log_if_camera_probe(const char *path) {
    if (strstr(path, "/dev/video") || strstr(path, "/dev/media") || strstr(path, "/dev/v4l")) {
        fprintf(stderr, "[hwid_stub] CAMERA PROBE open(%s)\n", path);
        fflush(stderr);
    }
}

/* Diagnostic only (not yet faked): flags magnetometer/IMU (IIO) and VCM
 * focuser probes so we can see exactly which paths the binary touches for
 * compass_sensor/balance_sensor/second_focuser before deciding whether to
 * stub them. */
static void log_if_sensor_probe(const char *path) {
    if (strstr(path, "/sys/bus/iio") || strstr(path, "/dev/iio") ||
        strstr(path, "5-000c") || strstr(path, "dw9800")) {
        fprintf(stderr, "[hwid_stub] SENSOR PROBE open(%s)\n", path);
        fflush(stderr);
    }
}

/* Redirect /dev/video*, /dev/media*, /dev/v4l-subdev* to /dev/null so the
 * binary's ASICAM layer can open them without ENOENT.  Track the resulting fds
 * so ioctl() can return 0 for all V4L2 requests sent to them. */
static int open_camera_dev(const char *path, int flags, int mode,
                            int (*real)(const char *, int, ...)) {
    int fd = real("/dev/null", flags, mode);
    /* Differentiate RAW sensor (/dev/video0) from YUV ISP output (/dev/video4).
     * ASICAM validates DQBUF bytesused against different stride formulas per path. */
    cam_fd_type_t type = CAM_FD_TYPE_GENERIC;
    if (strstr(path, "/dev/video0")) type = CAM_FD_TYPE_RAW;
    else if (strstr(path, "/dev/video4")) type = CAM_FD_TYPE_YUV;
    cam_fd_add(fd, type);
    fprintf(stderr, "[hwid_stub] camera dev open(%s) -> /dev/null fd=%d type=%d\n", path, fd, type);
    fflush(stderr);
    return fd;
}

static int is_camera_dev(const char *path) {
    return strstr(path, "/dev/video") || strstr(path, "/dev/media") ||
           strstr(path, "/dev/v4l");
}

/* The firmware's plate-solve pipeline reads the camera-derived FITS at this
 * fixed path.  We serve a rendered replacement (SOLVE_DST) instead, but ONLY for
 * content reads: a READ open of SOLVE_SRC is redirected to SOLVE_DST.  Writes
 * pass through untouched, so the imager still creates a real SOLVE_SRC file from
 * its (flat-gray) capture — that real file is what stat-based tools in the
 * solve-field pipeline (`file`, run by image2pnm) stat, while every actual read
 * of its contents is served our rendered FITS.  This keeps stat() and open()
 * consistent without a symlink. */
static const char *SOLVE_SRC = "/tmp/zwo/solvetmp.fit";
static const char *SOLVE_DST = "/run/seestar-sim/solve.fits";

static const char *solve_redirect(const char *path, int flags) {
    if (!path) return path;
    size_t n = strlen(path), m = strlen(SOLVE_SRC);
    if (n < m || strcmp(path + n - m, SOLVE_SRC) != 0) return path;
    if ((flags & O_ACCMODE) != O_RDONLY) return path;    /* let the imager's write create the real file */
    /* Only redirect reads in solve-field & its helper children — NOT the imager
     * itself, whose cfitsio save of solvetmp.fit does a read-mode existence
     * check that we must not hijack (doing so breaks its file creation). */
    if (is_imager_process()) return path;
    if (access(SOLVE_DST, R_OK) != 0) return path;       /* no render yet */
    fprintf(stderr, "[hwid_stub] redirect solve read %s -> %s\n", path, SOLVE_DST);
    fflush(stderr);
    return SOLVE_DST;
}

int open(const char *path, int flags, ...) {
    static int (*real)(const char *, int, ...) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "open");
    int mode = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); }
    if (path) {
        path = solve_redirect(path, flags);
        log_if_camera_probe(path);
        log_if_sensor_probe(path);
        int fd = fd_for_path(path); if (fd != -2) return fd;
        if (strcmp(path, EAF_MISC_PATH) == 0) {
            eaf_fd = real("/dev/null", flags, mode);
            fprintf(stderr, "[hwid_stub] open(%s) -> /dev/null fd=%d\n", path, eaf_fd);
            fflush(stderr);
            return eaf_fd;
        }
        if (strcmp(path, PWM_MISC_PATH) == 0) {
            pwm_fd = real("/dev/null", flags, mode);
            fprintf(stderr, "[hwid_stub] open(%s) -> /dev/null fd=%d (EFW)\n", path, pwm_fd);
            fflush(stderr);
            return pwm_fd;
        }
        if (is_camera_dev(path)) return open_camera_dev(path, flags, mode, real);
    }
    return real(path, flags, mode);
}

int open64(const char *path, int flags, ...) {
    static int (*real)(const char *, int, ...) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "open64");
    int mode = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); }
    if (path) {
        path = solve_redirect(path, flags);
        log_if_camera_probe(path);
        log_if_sensor_probe(path);
        int fd = fd_for_path(path); if (fd != -2) return fd;
        if (strcmp(path, EAF_MISC_PATH) == 0) {
            eaf_fd = real("/dev/null", flags, mode);
            fprintf(stderr, "[hwid_stub] open64(%s) -> /dev/null fd=%d\n", path, eaf_fd);
            fflush(stderr);
            return eaf_fd;
        }
        if (strcmp(path, PWM_MISC_PATH) == 0) {
            pwm_fd = real("/dev/null", flags, mode);
            fprintf(stderr, "[hwid_stub] open64(%s) -> /dev/null fd=%d (EFW)\n", path, pwm_fd);
            fflush(stderr);
            return pwm_fd;
        }
        if (is_camera_dev(path)) return open_camera_dev(path, flags, mode, real);
    }
    return real(path, flags, mode);
}

int openat(int dirfd, const char *path, int flags, ...) {
    static int (*real_open)(const char *, int, ...) = NULL;
    static int (*real)(int, const char *, int, ...) = NULL;
    if (!real_open) real_open = dlsym(RTLD_NEXT, "open");
    if (!real) real = dlsym(RTLD_NEXT, "openat");
    int mode = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); }
    if (path) {
        path = solve_redirect(path, flags);
        log_if_camera_probe(path);
        log_if_sensor_probe(path);
        int fd = fd_for_path(path); if (fd != -2) return fd;
        if (strcmp(path, EAF_MISC_PATH) == 0) {
            eaf_fd = real_open("/dev/null", flags, mode);
            fprintf(stderr, "[hwid_stub] openat(%s) -> /dev/null fd=%d\n", path, eaf_fd);
            fflush(stderr);
            return eaf_fd;
        }
        if (strcmp(path, PWM_MISC_PATH) == 0) {
            pwm_fd = real_open("/dev/null", flags, mode);
            fprintf(stderr, "[hwid_stub] openat(%s) -> /dev/null fd=%d (EFW)\n", path, pwm_fd);
            fflush(stderr);
            return pwm_fd;
        }
        if (is_camera_dev(path)) return open_camera_dev(path, flags, mode, real_open);
    }
    return real(dirfd, path, flags, mode);
}

/* V4L2 ioctl constants (avoid depending on kernel headers version).
 * Computed as _IOC(dir, 'V', nr, sizeof(struct)) where dir: 1=W,2=R,3=RW.
 * All size fields match kernel 4.19 struct sizes. */
#define VIDIOC_QUERYCAP    0x80685600U  /* _IOR  'V'  0  struct v4l2_capability(104) */
#define VIDIOC_G_FMT       0xc0cc5604U  /* _IOWR 'V'  4  struct v4l2_format(204)     */
#define VIDIOC_S_FMT       0xc0cc5605U  /* _IOWR 'V'  5  struct v4l2_format(204)     */
#define VIDIOC_TRY_FMT     0xc0cc5640U  /* _IOWR 'V' 64  struct v4l2_format(204)     */

/* struct v4l2_capability field offsets */
#define V4L2_CAP_VIDEO_CAPTURE_MPLANE 0x00001000U  /* bit 12 in capabilities field */
#define V4L2_CAP_STREAMING            0x04000000U

/* struct v4l2_format layout for V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE (type=9):
 *   [  0] type (u32)          = 9
 *   [  4] pix_mp.width        = image width in pixels
 *   [  8] pix_mp.height       = image height in pixels
 *   [ 12] pix_mp.pixelformat  = V4L2_PIX_FMT_* fourcc
 *   [ 16] pix_mp.field        = 1 (V4L2_FIELD_NONE)
 *   [ 20] pix_mp.colorspace   = 0
 *   [ 24] pix_mp.plane_fmt[0].sizeimage    (4)
 *   [ 28] pix_mp.plane_fmt[0].bytesperline (4)
 *   [ 32..43] plane_fmt[0].reserved (12)
 *   [180] pix_mp.num_planes   (u8) = 1
 * Total: 204 bytes */
#define V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE  9U
/* V4L2_PIX_FMT_SGBRG10 = v4l2_fourcc('B','G','1','0') — 10-bit Bayer for IMX462 RAW */
#define V4L2_PIX_FMT_SGBRG10  0x30314742U

/* Sensor resolution — runtime, model-aware (same env logic as camera_sensor_name()).
 * S50/S50V2  : IMX462 → 1920×1080
 * S50P/S30P  : IMX585 → 3856×2180  (Sony STARVIS 2, 8.3 MP; verify with real HW)
 * S30        : IMX662 → 1920×1080  (TODO: confirm IMX662 native crop used by binary)
 * Default    : 1920×1080
 */
static uint32_t sensor_width(void) {
    const char *m = getenv("SEESTAR_MODEL");
    if (m && (strcmp(m,"S30P")==0 || strcmp(m,"S50P")==0)) return 3856U;
    return 1920U;
}
static uint32_t sensor_height(void) {
    const char *m = getenv("SEESTAR_MODEL");
    if (m && (strcmp(m,"S30P")==0 || strcmp(m,"S50P")==0)) return 2180U;
    return 1080U;
}

/* RAW10 Bayer stride (/dev/video0): ((width*10/8 + 255)>>8)*256 bytes/line.
 * Matches ASICAM_GetImage check: cmp bytesused, height*r3 lsl#8
 * where r3 = ((width*10/8+255)>>8). For 1920: stride=2560 → total=2,764,800.
 *                                   For 3856: stride=4864 → total=10,603,520. */
static uint32_t raw_stride_bytes(void) {
    return ((sensor_width() * 10 / 8 + 255) >> 8) * 256;
}
static uint32_t raw_frame_bytes(void) { return sensor_height() * raw_stride_bytes(); }

/* NV12/YUV420 stride (/dev/video4 ISP output): ((width*3/2 + 255)>>8)*256 bytes/line.
 * Matches ASICAM_GetImage check: cmp sp+44, height*r1 lsl#8
 * where r1 = ((width*3/2+255)>>8). For 1920: stride=3072 → total=3,317,760.
 *                                   For 3856: stride=5888 → total=12,836,640. */
static uint32_t yuv_stride_bytes(void) {
    return ((sensor_width() * 3 / 2 + 255) >> 8) * 256;
}
static uint32_t yuv_frame_bytes(void) { return sensor_height() * yuv_stride_bytes(); }

/* Shared frame buffer alias — YUV is always larger than RAW10 for same dimensions. */
static uint32_t frame_bytes(void) { return yuv_frame_bytes(); }

/* V4L2 streaming ioctl constants (kernel 4.19 ARM32 struct sizes).
 * Encoding: (dir<<30)|(size<<16)|('V'<<8)|nr; dir: 1=W,2=R,3=RW. */
#define VIDIOC_REQBUFS   0xc0145608U  /* _IOWR 'V'  8  v4l2_requestbuffers(20) */
#define VIDIOC_QUERYBUF  0xc0445609U  /* _IOWR 'V'  9  v4l2_buffer(68)         */
#define VIDIOC_QBUF      0xc044560fU  /* _IOWR 'V' 15  v4l2_buffer(68)         */
#define VIDIOC_DQBUF     0xc0445611U  /* _IOWR 'V' 17  v4l2_buffer(68)         */
#define VIDIOC_STREAMON  0x40045612U  /* _IOW  'V' 18  int(4)                   */
#define VIDIOC_STREAMOFF 0x40045613U  /* _IOW  'V' 19  int(4)                   */
/* Selection / crop API */
#define VIDIOC_S_CROP    0x4014563cU  /* _IOW  'V' 60  v4l2_crop(20)            */
#define VIDIOC_G_CROP    0xc014563bU  /* _IOWR 'V' 59  v4l2_crop(20)            */
#define VIDIOC_G_SELECTION 0xc040565eU /* _IOWR 'V' 94  v4l2_selection(64)      */
#define VIDIOC_S_SELECTION 0xc040565fU /* _IOWR 'V' 95  v4l2_selection(64)      */
/* struct v4l2_selection offsets: [0]=type [4]=target [8]=flags
 *  [12]=r.left [16]=r.top [20]=r.width [24]=r.height [28..63]=reserved */

/* struct v4l2_buffer (68 bytes, ARM32) field offsets used below */
#define V4LBUFoff_INDEX   0   /* u32 buffer index */
#define V4LBUFoff_BUSED   8   /* u32 bytesused (single-plane) */
#define V4LBUFoff_FLAGS  12   /* u32 flags */
#define V4LBUFoff_PLANES 52   /* u32 (pointer to struct v4l2_plane[]) */
#define V4LBUFoff_LEN    56   /* u32 num_planes for MPLANE */

/* struct v4l2_plane (60 bytes) field offsets */
#define V4LPLoff_BYTESUSED  0   /* u32 */
#define V4LPLoff_LENGTH     4   /* u32 */
#define V4LPLoff_MEM_OFFSET 8   /* u32 (mmap offset in union) */
#define V4LPLoff_DATA_OFF  12   /* u32 */

/* One shared synthetic frame, flat neutral gray (see get_cam_frame_buf), sized
 * to the largest layout the binary may read.  All
 * mmap() calls on tracked camera fds return this buffer regardless of the buffer
 * index — the binary just needs a readable/writable region with a plausible
 * frame in it.                                                               */
static uint8_t *_cam_frame_buf = NULL;
static size_t   _cam_frame_buf_sz = 0;

/* Filter wheel position tracking for dark-frame simulation: CreateDarkFunc
 * moves the wheel to position 0 (the "dark" slot — confirmed via the
 * firmware's own log lines "filter 1->0" before capture, "restore filter 1"
 * after) before capturing, then compares the frame's average pixel value
 * against a low threshold (observed ~700) to confirm the sensor is actually
 * blocked. A flat mid-gray fill fails that check unconditionally (average
 * ~8736), so CreateMasterDarkFrame retries once, gives up, and the whole
 * DarkLibrary operation reports "error":"move failed" — a red herring; the
 * wheel moved fine, the frame just never looked dark.
 * We don't decode the real EFW ioctl payload (it's an unvarying trigger
 * byte, not a position — see stub_mount.c-style comments elsewhere in this
 * file); instead we observe the position the firmware itself reports in its
 * own outgoing "Event":"WheelMove","state":"complete","position":N
 * notification (see observe_wheel_position() near write()/send() below) and
 * condition the synthetic frame's fill value on that. */
#define WHEEL_POS_DARK   0
#define CAM_FILL_NORMAL  0x40  /* existing flat mid-gray, used for every non-dark position */
#define CAM_FILL_DARK    0x00  /* near-black, satisfies the average-brightness dark check */
static volatile int g_wheel_position  = 1;  /* last position seen in a WheelMove complete event */
static int          g_frame_fill_state = 1; /* which position the buffer currently reflects */

/* Refill the synthetic frame buffer's fill value if the tracked wheel
 * position has changed since the last fill (cheap: only memsets on an
 * actual position change, not on every DQBUF). */
static void refill_cam_frame_for_wheel(void) {
    if (!_cam_frame_buf || g_frame_fill_state == g_wheel_position) return;
    uint8_t fill = (g_wheel_position == WHEEL_POS_DARK) ? CAM_FILL_DARK : CAM_FILL_NORMAL;
    memset(_cam_frame_buf, fill, _cam_frame_buf_sz);
    g_frame_fill_state = g_wheel_position;
    fprintf(stderr, "[hwid_stub] cam frame buf refilled for wheel position %d (fill=0x%02x)\n",
            g_wheel_position, fill);
    fflush(stderr);
}

static uint8_t *get_cam_frame_buf(void) {
    if (_cam_frame_buf) return _cam_frame_buf;
    static void *(*real_mmap)(void *, size_t, int, int, int, off_t) = NULL;
    if (!real_mmap) real_mmap = dlsym(RTLD_NEXT, "mmap");
    uint32_t W = sensor_width(), H = sensor_height();
    /* Size for the LARGEST layout the binary may read from this buffer, not just
     * the NV12 size we report in DQBUF.  The star/exposure path does
     * `ReallocBuf 4147200` = W*H*2 (16-bit raw); if it copies its own expected
     * 16-bit frame size rather than the DQBUF bytesused, an NV12-sized (810-page)
     * mapping would be over-read by ~829 KB → SIGSEGV.  Allocate max(NV12, raw16)
     * so any such over-read stays inside a mapped, initialized region. */
    size_t nv12  = frame_bytes();
    size_t raw16 = (size_t)W * H * 2;
    size_t bufsz = nv12 > raw16 ? nv12 : raw16;
    /* Confirmed crash (v3.x): the exposure/star path memcpy's its ReallocBuf
     * size (raw16 = W*H*2) out of this buffer.  Sizing to raw16 covers that;
     * the +64 KiB margin absorbs any slightly-larger read (e.g. a debayer that
     * steps one row past the last pixel) so it can't fault at the mapping edge. */
    bufsz += 65536;
    void *p = real_mmap(NULL, bufsz, PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) return NULL;
    _cam_frame_buf = p;
    _cam_frame_buf_sz = bufsz;
    /* Flat neutral gray.  The live feed is the binary's *transform* of this
     * buffer (reshape/stride/debayer into the port-4800 output), whose exact
     * geometry we don't model — so any structured test pattern (per-row or
     * raster gradient) gets reshaped into stride-aliased banding.  A constant is
     * the one fill that survives an arbitrary linear transform unchanged, so it
     * always renders as a clean, uniform frame regardless of the consumer's
     * assumed width/format.  (To produce a *realistic* pattern instead, capture
     * the port-4800 bytes for a known input and reverse the transform first.) */
    memset(_cam_frame_buf, CAM_FILL_NORMAL, bufsz);
    fprintf(stderr, "[hwid_stub] fake frame buffer %zu bytes at %p (sensor %ux%u, nv12=%zu raw16=%zu)\n",
            bufsz, (void *)_cam_frame_buf, W, H, nv12, raw16);
    fflush(stderr);
    return _cam_frame_buf;
}

/* Write bytesused/length/mem_offset into the first struct v4l2_plane.
 * planes_ptr is read from v4l2_buffer.m.planes (a 32-bit pointer in the arg). */
static void fill_plane_struct(uint32_t planes_ptr, uint32_t bytesused) {
    uint8_t *pl = (uint8_t *)(uintptr_t)planes_ptr;
    if (!pl) return;
    uint32_t zero = 0;
    memcpy(pl + V4LPLoff_BYTESUSED,  &bytesused, 4);
    memcpy(pl + V4LPLoff_LENGTH,     &bytesused, 4);
    memcpy(pl + V4LPLoff_MEM_OFFSET, &zero,      4);  /* offset 0 into mmap'd buf */
    memcpy(pl + V4LPLoff_DATA_OFF,   &zero,      4);
}

/* Return frame size for a given camera fd.
 * In camera_simulate=1 mode the binary uses /dev/video0 for NV12 output even
 * though it is the declared RAW device.  ASICAM_GetImage's cam_id=0 path checks
 * bytesused against the NV12 stride formula (3,317,760).  Always return
 * yuv_frame_bytes() so that check passes regardless of which fd is active. */
static uint32_t cam_fd_frame_bytes(int fd) {
    (void)fd;
    return yuv_frame_bytes();
}

/* V4L2_PIX_FMT_NV12 = v4l2_fourcc('N','V','1','2') — NV12 semi-planar YUV420 */
#define V4L2_PIX_FMT_NV12  0x3231564EU

static void fill_v4l2_format_mplane(uint8_t *fmt, uint32_t w, uint32_t h, cam_fd_type_t type) {
    uint32_t fmttype = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    uint32_t field  = 1;  /* V4L2_FIELD_NONE */
    uint32_t pixfmt, bpl, sz;
    if (type == CAM_FD_TYPE_YUV) {
        /* NV12: ISP output, ((w*3/2+255)>>8)*256 is total/row in binary's formula */
        pixfmt = V4L2_PIX_FMT_NV12;
        bpl    = ((w * 3 / 2 + 255) >> 8) * 256;
        sz     = h * bpl;
    } else {
        /* RAW10 Bayer: matches ASICAM stride check at VA 0x2b9458 */
        pixfmt = V4L2_PIX_FMT_SGBRG10;
        bpl    = ((w * 10 / 8 + 255) >> 8) * 256;
        sz     = h * bpl;
    }
    memset(fmt, 0, 204);
    memcpy(fmt +  0, &fmttype, 4);
    memcpy(fmt +  4, &w,      4);
    memcpy(fmt +  8, &h,      4);
    memcpy(fmt + 12, &pixfmt, 4);
    memcpy(fmt + 16, &field,  4);
    memcpy(fmt + 24, &sz,     4);  /* plane_fmt[0].sizeimage */
    memcpy(fmt + 28, &bpl,    4);  /* plane_fmt[0].bytesperline */
    fmt[180] = 1;                  /* num_planes = 1 */
}

/* EAF ioctls (type 'E') all faked as success. The driver protocol is
 * undocumented; observed requests (_IOW 'E' 2/4/5/6/8, _IOR 'E' 1) appear to
 * be init/move/stop/position-poll calls that only check the ioctl() return
 * value, not the buffer contents — eaf_open() succeeds and get_device_state
 * reports a stable focuser position once these return 0 instead of erroring.
 *
 * Camera V4L2 ioctls: return 0 for all, with key structs populated.
 * VIDIOC_QUERYCAP must report V4L2_CAP_VIDEO_CAPTURE_MPLANE so v4l2_open
 * in the binary doesn't abort with "neither video capture (mplane) nor video
 * output supported". All other ioctls return 0 with zeroed buffers for now. */
int ioctl(int fd, unsigned long request, ...) {
    static int (*real)(int, unsigned long, ...) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "ioctl");
    void *arg;
    va_list ap; va_start(ap, request); arg = va_arg(ap, void *); va_end(ap);
    if (fd == eaf_fd && fd != -1) return 0;
    if (fd == pwm_fd && fd != -1) {
        /* EFW: echo the last SET 8-byte state back on GET so the imager's poll
         * loop sees the wheel arrive; other pwm-gpio-misc ioctls just succeed. */
        if (request == EFW_SET && arg) {
            /* The binary re-asserts the same target state on every poll tick
             * while waiting for the wheel to arrive, not just on actual moves.
             * Only log when the state changes so this doesn't spam identically. */
            if (memcmp(efw_state, arg, sizeof(efw_state)) != 0) {
                memcpy(efw_state, arg, sizeof(efw_state));
                fprintf(stderr, "[hwid_stub] EFW set %02x%02x%02x%02x %02x%02x%02x%02x\n",
                        efw_state[0], efw_state[1], efw_state[2], efw_state[3],
                        efw_state[4], efw_state[5], efw_state[6], efw_state[7]);
                fflush(stderr);
            }
            return 0;
        }
        if (request == EFW_GET && arg) { memcpy(arg, efw_state, sizeof(efw_state)); return 0; }
        return 0;
    }
    if (cam_fd_is_tracked(fd)) {
        if (cam_verbose()) {
            fprintf(stderr, "[hwid_stub] camera ioctl fd=%d req=0x%08lx\n", fd, request);
            fflush(stderr);
        }
        if (request == VIDIOC_QUERYCAP && arg) {
            /* struct v4l2_capability: [0] driver[16], [16] card[32], [48] bus_info[32],
             *                         [80] version, [84] capabilities, [88] device_caps */
            uint8_t *cap = (uint8_t *)arg;
            uint32_t caps = V4L2_CAP_VIDEO_CAPTURE_MPLANE | V4L2_CAP_STREAMING;
            memset(cap, 0, 104);
            strncpy((char *)cap,      "fake_cam",       16);
            strncpy((char *)cap + 16, camera_sensor_name(), 32);
            strncpy((char *)cap + 48, "platform:rkcif", 32);
            memcpy(cap + 84, &caps, 4);
            memcpy(cap + 88, &caps, 4);
            fprintf(stderr, "[hwid_stub] VIDIOC_QUERYCAP → caps=0x%08x\n", caps);
            fflush(stderr);
        } else if ((request == VIDIOC_G_FMT || request == VIDIOC_S_FMT ||
                    request == VIDIOC_TRY_FMT) && arg) {
            /* Log what the binary sent first (type, width, height at offsets 0/4/8) */
            uint8_t *fmt = (uint8_t *)arg;
            uint32_t in_type, in_w, in_h;
            memcpy(&in_type, fmt + 0, 4);
            memcpy(&in_w,    fmt + 4, 4);
            memcpy(&in_h,    fmt + 8, 4);
            fprintf(stderr, "[hwid_stub] V4L2_FMT(req=0x%lx) in: type=%u %ux%u\n",
                    request, in_type, in_w, in_h);
            /* Return 1920x1080 regardless of what was requested.  The binary reads
             * back width/height from this buffer as the camera's active resolution;
             * without this fill, width=height=0 maps to chip_size=[-1,-1]. */
            cam_fd_type_t fdtype = cam_fd_get_type(fd);
            uint32_t sw = sensor_width(), sh = sensor_height();
            fill_v4l2_format_mplane(fmt, sw, sh, fdtype);
            fprintf(stderr, "[hwid_stub] V4L2_FMT → %ux%u %s MPLANE\n",
                    sw, sh,
                    fdtype == CAM_FD_TYPE_YUV ? "NV12" : "SGBRG10");
            fflush(stderr);
        } else if ((request == VIDIOC_G_SELECTION || request == VIDIOC_S_SELECTION) && arg) {
            /* struct v4l2_selection: [0]=type [4]=target [8]=flags
             *   [12]=r.left [16]=r.top [20]=r.width [24]=r.height [28..63]=reserved
             * Return full-sensor active area so the binary doesn't abort on EINVAL. */
            uint8_t *sel = (uint8_t *)arg;
            uint32_t target, zero = 0, w = sensor_width(), h = sensor_height();
            memcpy(&target, sel + 4, 4);
            memcpy(sel + 12, &zero, 4);   /* r.left */
            memcpy(sel + 16, &zero, 4);   /* r.top */
            memcpy(sel + 20, &w,    4);   /* r.width */
            memcpy(sel + 24, &h,    4);   /* r.height */
            fprintf(stderr, "[hwid_stub] %s target=%u → 0,0,%u,%u\n",
                    request == VIDIOC_G_SELECTION ? "G_SELECTION" : "S_SELECTION",
                    target, w, h);
            fflush(stderr);
        } else if ((request == VIDIOC_G_CROP || request == VIDIOC_S_CROP) && arg) {
            /* struct v4l2_crop: [0]=type [4]=c.left [8]=c.top [12]=c.width [16]=c.height */
            uint8_t *crop = (uint8_t *)arg;
            uint32_t zero = 0, w = sensor_width(), h = sensor_height();
            memcpy(crop + 4,  &zero, 4);
            memcpy(crop + 8,  &zero, 4);
            memcpy(crop + 12, &w,    4);
            memcpy(crop + 16, &h,    4);
        } else if (request == VIDIOC_REQBUFS && arg) {
            /* struct v4l2_requestbuffers [0]=count [4]=type [8]=memory [12..19]=reserved */
            uint8_t *req = (uint8_t *)arg;
            uint32_t count, type, memory;
            memcpy(&count,  req + 0, 4);
            memcpy(&type,   req + 4, 4);
            memcpy(&memory, req + 8, 4);
            uint32_t orig_count = count;
            if (count == 0) {
                /* binary is freeing buffers — do not override */
            } else {
                get_cam_frame_buf();  /* pre-allocate frame memory on first alloc */
            }
            memcpy(req + 0, &count, 4);
            fprintf(stderr, "[hwid_stub] VIDIOC_REQBUFS orig=%u count=%u type=%u memory=%u\n",
                    orig_count, count, type, memory);
            fflush(stderr);
        } else if (request == VIDIOC_QUERYBUF && arg) {
            uint8_t *buf = (uint8_t *)arg;
            uint32_t idx, planes_ptr, fbytes = cam_fd_frame_bytes(fd), zero = 0;
            memcpy(&idx,        buf + V4LBUFoff_INDEX,  4);
            memcpy(&planes_ptr, buf + V4LBUFoff_PLANES, 4);
            /* The ASICAM layer uses m.offset/length (non-MPLANE style) even when
             * REQBUFS used type=9.  Fill both: planes array if non-NULL, and
             * always set m.offset=0 + length=fbytes at the union position. */
            if (planes_ptr) fill_plane_struct(planes_ptr, fbytes);
            memcpy(buf + V4LBUFoff_PLANES, &zero,   4);  /* m.offset = 0 */
            memcpy(buf + V4LBUFoff_LEN,    &fbytes, 4);  /* length in bytes */
            fprintf(stderr, "[hwid_stub] VIDIOC_QUERYBUF idx=%u planes@0x%08x → m.offset=0 len=%u\n",
                    idx, planes_ptr, fbytes);
            fflush(stderr);
        } else if (request == VIDIOC_QBUF && arg) {
            uint32_t idx; memcpy(&idx, (uint8_t *)arg + V4LBUFoff_INDEX, 4);
            if (cam_verbose()) {
                fprintf(stderr, "[hwid_stub] VIDIOC_QBUF idx=%u\n", idx);
                fflush(stderr);
            }
        } else if (request == VIDIOC_DQBUF && arg) {
            /* Throttle to ~30 fps so the binary doesn't spin-loop */
            struct timespec ts = {0, 33333333L};
            nanosleep(&ts, NULL);
            refill_cam_frame_for_wheel();
            static uint32_t _frame_seq = 0;
            static uint32_t _buf_idx   = 0;
            uint8_t *buf = (uint8_t *)arg;
            uint32_t fbytes = cam_fd_frame_bytes(fd);
            uint32_t planes_ptr;
            memcpy(&planes_ptr, buf + V4LBUFoff_PLANES, 4);
            fill_plane_struct(planes_ptr, fbytes);

            struct timespec now;
            clock_gettime(CLOCK_MONOTONIC, &now);
            uint32_t tv_sec  = (uint32_t)now.tv_sec;
            uint32_t tv_usec = (uint32_t)(now.tv_nsec / 1000U);
            uint32_t idx     = _buf_idx;
            uint32_t seq     = _frame_seq++;
            uint32_t type    = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
            /* V4L2_BUF_FLAG_MAPPED=0x1 | V4L2_BUF_FLAG_DONE=0x4 |
             * V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC=0x2000 */
            uint32_t flags   = 0x00002005U;
            uint32_t memory  = 1U;   /* V4L2_MEMORY_MMAP */
            uint32_t zero    = 0;
            _buf_idx = (_buf_idx + 1) % 3;

            memcpy(buf + V4LBUFoff_INDEX,  &idx,     4);
            memcpy(buf + 4,                &type,    4);  /* buf.type */
            memcpy(buf + V4LBUFoff_BUSED,  &fbytes,  4);
            memcpy(buf + V4LBUFoff_FLAGS,  &flags,   4);
            memcpy(buf + 20,               &tv_sec,  4);  /* timestamp.tv_sec */
            memcpy(buf + 24,               &tv_usec, 4);  /* timestamp.tv_usec */
            memcpy(buf + 44,               &seq,     4);  /* sequence */
            memcpy(buf + 48,               &memory,  4);  /* memory */
            memcpy(buf + V4LBUFoff_PLANES, &zero,    4);  /* m.offset = 0 */
            memcpy(buf + V4LBUFoff_LEN,    &fbytes,  4);
            if (cam_verbose()) {
                fprintf(stderr, "[hwid_stub] VIDIOC_DQBUF fd=%d type=%d fbytes=%u planes@0x%08x → idx=%u seq=%u\n",
                        fd, (int)cam_fd_get_type(fd), fbytes, planes_ptr, idx, seq);
                fflush(stderr);
            }
        } else if (request == VIDIOC_STREAMON && arg) {
            _streaming = 1;
            fprintf(stderr, "[hwid_stub] VIDIOC_STREAMON type=%u → streaming=1\n",
                    *(uint32_t *)arg);
            fflush(stderr);
        } else if (request == VIDIOC_STREAMOFF && arg) {
            _streaming = 0; _frame_fd = -1;
            fprintf(stderr, "[hwid_stub] VIDIOC_STREAMOFF type=%u → streaming=0\n",
                    *(uint32_t *)arg);
            fflush(stderr);
        }
        return 0;
    }
    return real(fd, request, arg);
}

/* mmap/mmap64 interception: when the binary memory-maps a camera fd (redirected
 * to /dev/null, which doesn't support mmap), return our pre-allocated synthetic
 * frame buffer instead.  The buffer index's mmap offset is ignored — all slots
 * share the same grey test-pattern frame. */
void *mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset) {
    static void *(*real)(void *, size_t, int, int, int, off_t) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "mmap");
    if (cam_fd_is_tracked(fd)) {
        uint8_t *buf = get_cam_frame_buf();
        fprintf(stderr, "[hwid_stub] mmap(fd=%d len=%zu off=%ld) → %p\n",
                fd, length, (long)offset, (void *)buf);
        fflush(stderr);
        return buf ? (void *)buf : MAP_FAILED;
    }
    return real(addr, length, prot, flags, fd, offset);
}

void *mmap64(void *addr, size_t length, int prot, int flags, int fd, off64_t offset) {
    static void *(*real)(void *, size_t, int, int, int, off64_t) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "mmap64");
    if (cam_fd_is_tracked(fd)) {
        uint8_t *buf = get_cam_frame_buf();
        fprintf(stderr, "[hwid_stub] mmap64(fd=%d len=%zu off=%lld) → %p\n",
                fd, length, (long long)offset, (void *)buf);
        fflush(stderr);
        return buf ? (void *)buf : MAP_FAILED;
    }
    return real(addr, length, prot, flags, fd, offset);
}

/* munmap/munmap64: the binary calls these on the camera-fd mmap it thinks it
 * owns whenever it closes/reopens the camera (e.g. switching preview → focus
 * → star mode for a GOTO capture, or ASICAM_StopCapture/Close in general).
 * Our mmap()/mmap64() interceptor always hands back the SAME cached
 * _cam_frame_buf regardless of which V4L2 buffer index was requested — so a
 * real munmap() of that address here would unmap the one persistent backing
 * region, leaving `_cam_frame_buf` a dangling pointer.  The next camera open
 * calls get_cam_frame_buf() again, sees the cached (now-invalid) pointer, and
 * hands it straight back without remapping → the app's very next read/copy
 * from that address SIGSEGVs at the buffer's base (confirmed: this is the
 * GOTO-after-polar-align / GOTO-after-full-startup crash, where a prior
 * camera session's clean close-and-reopen is exactly what tears down the
 * mapping before the GOTO capture reuses it).  Swallow munmap on our buffer's
 * range as a no-op; only real, non-synthetic mappings get unmapped for real. */
static int addr_in_cam_frame_buf(void *addr) {
    if (!_cam_frame_buf) return 0;
    uintptr_t a = (uintptr_t)addr, base = (uintptr_t)_cam_frame_buf;
    return a >= base && a < base + _cam_frame_buf_sz;
}
int munmap(void *addr, size_t length) {
    static int (*real)(void *, size_t) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "munmap");
    if (addr_in_cam_frame_buf(addr)) {
        fprintf(stderr, "[hwid_stub] munmap(%p len=%zu) on cam frame buf — swallowed (no-op)\n",
                addr, length);
        fflush(stderr);
        return 0;
    }
    return real(addr, length);
}

FILE *fopen(const char *path, const char *mode) {
    static FILE *(*real)(const char *, const char *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "fopen");
    if (path) {
        /* cfitsio (solve-field/image2xy) opens the solve FITS via buffered
         * stdio, which bypasses the open/open64/openat interposers — so apply
         * the same redirect here.  Map the stdio mode to a read/write intent:
         * read-mode opens of solvetmp.fit serve the render; writes pass through
         * (solve_redirect only touches O_RDONLY). */
        if (mode) {
            int rdonly = (mode[0] == 'r' && !strchr(mode, '+'));
            path = solve_redirect(path, rdonly ? O_RDONLY : O_WRONLY);
        }
        int fd = fd_for_path(path);
        if (fd != -2) return fd >= 0 ? fdopen(fd, "r") : NULL;
    }
    return real(path, mode);
}

FILE *fopen64(const char *path, const char *mode) {
    return fopen(path, mode);
}

/* stat/access intercepts: log any probe of camera device paths so we can see
 * what the binary checks before "get media info failed" fires.  No faking yet
 * — just diagnostic logging. */
int stat(const char *path, struct stat *buf) {
    static int (*real)(const char *, struct stat *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "stat");
    if (path && (strstr(path, "/dev/video") || strstr(path, "/dev/media") ||
                 strstr(path, "/dev/v4l") || strstr(path, "video4linux"))) {
        fprintf(stderr, "[hwid_stub] stat(%s)\n", path);
        fflush(stderr);
    }
    return real(path, buf);
}

int stat64(const char *path, struct stat64 *buf) {
    static int (*real)(const char *, struct stat64 *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "stat64");
    if (path && (strstr(path, "/dev/video") || strstr(path, "/dev/media") ||
                 strstr(path, "/dev/v4l") || strstr(path, "video4linux"))) {
        fprintf(stderr, "[hwid_stub] stat64(%s)\n", path);
        fflush(stderr);
    }
    return real(path, buf);
}

/* access() for camera device paths: fake success so ASICAM_Open doesn't abort
 * at the "get media info failed" check before even trying to open the device.
 * The subsequent open() intercept redirects the actual opens to /dev/null.
 *
 * Only expose /dev/media0 and /dev/media1.  The binary loops over media0..4
 * (checking access() before calling media_device_new); if media2+ also appear
 * accessible, the same fake device data gets reprocessed three more times,
 * overwriting output buffer fields and confusing the counter. Returning -1 for
 * media2+ causes the loop to terminate cleanly after the two real devices. */
int access(const char *path, int mode) {
    static int (*real)(const char *, int) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "access");
    if (path) {
        if (strstr(path, "/dev/video") || strstr(path, "/dev/v4l") ||
                strstr(path, "video4linux")) {
            fprintf(stderr, "[hwid_stub] access(%s, %d) -> 0\n", path, mode);
            fflush(stderr);
            return 0;
        }
        if (strstr(path, "/dev/media")) {
            if (strcmp(path, "/dev/media0") == 0 || strcmp(path, "/dev/media1") == 0) {
                fprintf(stderr, "[hwid_stub] access(%s, %d) -> 0\n", path, mode);
                fflush(stderr);
                return 0;
            }
            fprintf(stderr, "[hwid_stub] access(%s, %d) -> -1 (ENOENT, not exposed)\n", path, mode);
            fflush(stderr);
            errno = ENOENT;
            return -1;
        }
    }
    return real(path, mode);
}

/* popen interception: fake the camera-scan grep command.
 *
 * ASICAM_Scan runs: grep over /sys/class/video4linux/<dev>/name piped to
 * grep -E imx[0-9]+  (the glob would close a C block comment, so spelled out).
 * On real hardware the output is a line like:
 *   /sys/class/video4linux/v4l-subdev0/name:m00_b_imx462 1-001a
 * We intercept it and return the right sensor name for the current model.
 * All other popen calls go through unmodified. */
FILE *popen(const char *cmd, const char *type) {
    static FILE *(*real)(const char *, const char *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "popen");
    if (cmd && strstr(cmd, "video4linux") && strstr(cmd, "imx")) {
        const char *sensor = camera_sensor_name();
        char fake_cmd[256];
        /* printf outputs a plausible sysfs line whose last field matches imx[0-9]+ */
        snprintf(fake_cmd, sizeof(fake_cmd),
            "printf '/sys/class/video4linux/v4l-subdev0/name:m00_b_%s 1-001a\\n'", sensor);
        fprintf(stderr, "[hwid_stub] CAMERA SCAN popen intercepted -> sensor=%s\n", sensor);
        fflush(stderr);
        return real(fake_cmd, type);
    }
    return real(cmd, type);
}

/* Diagnostic only: log directory enumeration of the IIO sysfs tree so we
 * can see whether the binary scans /sys/bus/iio/devices/ to find the
 * magnetometer/IMU before deciding whether to fake its contents. */
DIR *opendir(const char *path) {
    static DIR *(*real)(const char *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "opendir");
    if (path && strstr(path, "/sys/bus/iio")) {
        fprintf(stderr, "[hwid_stub] SENSOR PROBE opendir(%s)\n", path);
        fflush(stderr);
    }
    return real(path);
}

/* AutoFocus spoof: the real AutoFocusFunc algorithm can't converge in the
 * sandbox (no real focuser position feedback, and the RKNN star-detector's
 * output tensor format is unknown/unimplemented). seestar_alp's
 * wait_end_op("AutoFocus") only inspects the "state" field of the
 * "Event":"AutoFocus" notification pushed over the control socket — nothing
 * else (error/code/etc.) matters to that decision. Rather than simulate the
 * real algorithm, rewrite that one field on the wire: "state":"fail" or
 * "state":"cancel" becomes "state":"complete" before the real write()/send()
 * sends it. Everything else (camera, focuser, RKNN stubs, the real internal
 * algorithm) is untouched and still "fails" internally exactly as before —
 * only the bytes leaving the process are patched.
 * See ~/dev/2026-07-19-autofocus-stub-design.md and
 * docs/superpowers/plans/2026-07-19-autofocus-stub.md for the full writeup. */
#define AF_MARKER      "\"Event\":\"AutoFocus\""
#define AF_COMPLETE    "\"state\":\"complete\""
#define AF_SCRATCH_CAP 4096

/* Replace the first occurrence of `needle` in buf[0..count) with AF_COMPLETE,
 * writing the result into out (capacity out_cap). Returns the new length on
 * success, or 0 if `needle` wasn't found or the result wouldn't fit. */
static size_t af_replace_needle(const char *buf, size_t count, const char *needle,
                                 char *out, size_t out_cap) {
    size_t nlen = strlen(needle);
    const void *hit = memmem(buf, count, needle, nlen);
    if (!hit) return 0;
    size_t prefix_len = (size_t)((const char *)hit - buf);
    size_t suffix_len = count - prefix_len - nlen;
    size_t rlen = strlen(AF_COMPLETE);
    size_t new_len = prefix_len + rlen + suffix_len;
    if (new_len >= out_cap) return 0;
    memcpy(out, buf, prefix_len);
    memcpy(out + prefix_len, AF_COMPLETE, rlen);
    memcpy(out + prefix_len + rlen, (const char *)hit + nlen, suffix_len);
    return new_len;
}

/* Returns the new length (>0) and fills `out` if buf[0..count) is an
 * "Event":"AutoFocus" notification with state "fail" or "cancel"; returns 0
 * (out untouched) for anything else, including non-matching writes. */
static size_t af_rewrite_if_fail(const void *buf, size_t count, char *out, size_t out_cap) {
    if (count == 0) return 0;
    if (!memmem(buf, count, AF_MARKER, strlen(AF_MARKER))) return 0;
    size_t n = af_replace_needle((const char *)buf, count, "\"state\":\"fail\"", out, out_cap);
    if (n) return n;
    return af_replace_needle((const char *)buf, count, "\"state\":\"cancel\"", out, out_cap);
}

/* Wheel-position observation (read-only — nothing is rewritten here): the
 * firmware's own "Event":"WheelMove","state":"complete","position":N
 * notification is the only reliable signal we have for which slot the wheel
 * is actually in (see g_wheel_position's declaration near the camera frame
 * buffer statics for why: the EFW ioctl SET payload doesn't vary by target
 * position). Scans buf[0..count) and updates g_wheel_position on a match. */
#define WM_MARKER  "\"Event\":\"WheelMove\""
static void observe_wheel_position(const void *buf, size_t count) {
    if (count == 0) return;
    if (!memmem(buf, count, WM_MARKER, strlen(WM_MARKER))) return;
    if (!memmem(buf, count, "\"state\":\"complete\"", strlen("\"state\":\"complete\""))) return;
    static const char pos_key[] = "\"position\":";
    const void *hit = memmem(buf, count, pos_key, strlen(pos_key));
    if (!hit) return;
    int val = atoi((const char *)hit + strlen(pos_key));
    g_wheel_position = val;
    fprintf(stderr, "[hwid_stub] observed WheelMove complete position=%d\n", val);
    fflush(stderr);
}

/* Live-view star injection: substitute the star-mode preview frame's pixel
 * payload (port-4800 stream) with a rendered synthetic starfield, without
 * needing to understand the firmware's internal raw-buffer->wire transform
 * (see docs/superpowers/specs/2026-07-22-live-view-star-injection-design.md).
 * Confirmed empirically (2026-07-22) that each frame is NOT one write() --
 * it's an 80-byte header (magic 03 c3 00 02 00 50) followed by a variable
 * number of payload write() calls on the SAME fd (observed: seven 524,288-byte
 * chunks + one 477,184-byte remainder = 4,147,200 bytes total, matching
 * frame_nbytes for the portrait S50 format) -- but chunk sizes are an
 * internal firmware buffer-size detail, not a stable contract, so this
 * tracks cumulative offset per fd rather than hardcoding chunk sizes/counts.
 * fd numbers are NOT stable across connections (observed both 25 and 26), so
 * the header's magic-byte CONTENT, not any fd value, is what starts tracking
 * a stream. send() is not touched: confirmed empirically the frame payload
 * only ever goes through write(). */
#define LIVE_RAW_PATH "/run/seestar-sim/live.raw"
#define LIVE_SEQ_PATH "/run/seestar-sim/live.seq"
static const uint8_t FRAME_HDR_MAGIC[6] = {0x03,0xc3,0x00,0x02,0x00,0x50};

static uint8_t *g_live_frame      = NULL;
static size_t   g_live_frame_sz   = 0;
static long     g_live_seq_cached = -1;

static long live_read_seq(void) {
    FILE *f = fopen(LIVE_SEQ_PATH, "r");
    if (!f) return -1;
    long seq = -1;
    if (fscanf(f, "%ld", &seq) != 1) seq = -1;
    fclose(f);
    return seq;
}

/* Per-fd cumulative payload offset for fds currently mid-stream. Small fixed
 * table: the firmware caps port-4800 at max_connec_num=2 concurrent
 * connections (see startServer log at container startup), so 8 entries is
 * generous headroom.
 *
 * Declared here (ahead of live_frame_refresh(), which needs live_stream_count
 * for its concurrency gate below) rather than down by live_stream_find() /
 * live_stream_start() / live_stream_end(), which stay in their original spot
 * since only the variables -- not those helper functions -- need to be
 * visible before this point. */
#define MAX_LIVE_STREAMS 8
static int    live_stream_fd[MAX_LIVE_STREAMS];
static size_t live_stream_off[MAX_LIVE_STREAMS];
static int    live_stream_count = 0;

/* Reloads g_live_frame from LIVE_RAW_PATH only when live.seq has changed
 * since the last load (renderd bumps it on every re-render), so a steady
 * pointing doesn't re-read a multi-MB file 10x/sec. Returns 1 if a usable
 * (possibly stale-but-valid) frame buffer is available, 0 if none has ever
 * loaded successfully. */
static int live_frame_refresh(void) {
    if (live_stream_count > 0) {
        /* A stream is currently mid-payload: is_frame_header() matched and
         * live_stream_start() ran for it, which only happens once
         * g_live_frame_sz > 0 -- i.e. g_live_frame is already loaded and
         * valid. Under max_connec_num=2, a second connection's header could
         * land here concurrently while this thread's write() interposer is
         * mid-copy out of g_live_frame; free()'ing it out from under that
         * copy would be a use-after-free (potential SIGSEGV), or at best
         * visible tearing (old-buffer bytes followed by new-buffer bytes
         * within one frame). Skip the reload entirely and reuse the current
         * buffer as-is; a moving pointing's content just updates one cycle
         * later, which is cosmetic, not a correctness issue. */
        return 1;
    }
    long seq = live_read_seq();
    if (seq < 0) return g_live_frame != NULL;
    if (seq == g_live_seq_cached && g_live_frame) return 1;
    FILE *f = fopen(LIVE_RAW_PATH, "rb");
    if (!f) return g_live_frame != NULL;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz <= 0) { fclose(f); return g_live_frame != NULL; }
    uint8_t *buf = malloc((size_t)sz);
    if (!buf) { fclose(f); return g_live_frame != NULL; }
    size_t rd = fread(buf, 1, (size_t)sz, f);
    fclose(f);
    if (rd != (size_t)sz) { free(buf); return g_live_frame != NULL; }
    free(g_live_frame);
    g_live_frame = buf;
    g_live_frame_sz = rd;
    g_live_seq_cached = seq;
    fprintf(stderr, "[hwid_stub] live frame reloaded: %zu bytes (seq=%ld)\n", rd, seq);
    fflush(stderr);
    return 1;
}

static int live_stream_find(int fd) {
    for (int i = 0; i < live_stream_count; i++) if (live_stream_fd[i] == fd) return i;
    return -1;
}
static void live_stream_start(int fd) {
    int idx = live_stream_find(fd);
    if (idx < 0) {
        idx = (live_stream_count < MAX_LIVE_STREAMS) ? live_stream_count++ : 0;
        live_stream_fd[idx] = fd;
    }
    live_stream_off[idx] = 0;
}
static void live_stream_end(int fd) {
    int idx = live_stream_find(fd);
    if (idx < 0) return;
    live_stream_count--;
    live_stream_fd[idx]  = live_stream_fd[live_stream_count];
    live_stream_off[idx] = live_stream_off[live_stream_count];
}

/* Header-shaped only: count==80 and the 6-byte magic matches. NOT sufficient
 * on its own to identify a real frame header -- the begin_streaming ack is
 * ALSO an 80-byte write() sharing this exact magic prefix (confirmed via
 * seestar_alp's own protocol struct, device/protocols/binary.py:122-124,
 * `>HHHIHHBBHH` big-endian: the first three H fields are these 6 magic
 * bytes, immediately followed by a 4-byte big-endian `size` field at byte
 * offset 6). See is_frame_header() below, which adds the size check that
 * actually disambiguates the two. */
static int is_header_shaped(const void *buf, size_t count) {
    return count == 80 && memcmp(buf, FRAME_HDR_MAGIC, sizeof(FRAME_HDR_MAGIC)) == 0;
}

/* True only when this is header-shaped AND its declared `size` field (big-
 * endian uint32 at byte offset 6, per the struct referenced above) matches
 * the currently-loaded live frame's byte count. A real frame header's size
 * is frame_nbytes (e.g. 4,147,200); the begin_streaming ack's header-shaped
 * chunk has size=4 (its tiny "done" payload) and must NOT match here, or its
 * 4-byte payload write gets mistaken for the first chunk of a live stream
 * and corrupted. Caller MUST call live_frame_refresh() before this so
 * g_live_frame_sz reflects the current frame (0/stale if none loaded yet,
 * in which case this always returns false -- fail open). */
static int is_frame_header(const void *buf, size_t count) {
    if (!is_header_shaped(buf, count)) return 0;
    const uint8_t *p = (const uint8_t *)buf;
    uint32_t size = ((uint32_t)p[6] << 24) | ((uint32_t)p[7] << 16) |
                    ((uint32_t)p[8] << 8)  |  (uint32_t)p[9];
    return g_live_frame_sz != 0 && size == g_live_frame_sz;
}

ssize_t write(int fd, const void *buf, size_t count) {
    static ssize_t (*real)(int, const void *, size_t) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "write");
    observe_wheel_position(buf, count);

    if (is_header_shaped(buf, count)) {
        live_frame_refresh();  /* must run before is_frame_header() below so
                                 * g_live_frame_sz is current for the size
                                 * comparison, not stale from a prior frame */
        if (is_frame_header(buf, count)) {
            live_stream_start(fd);
        } else {
            /* Header-shaped but size doesn't match the live frame -- e.g.
             * the begin_streaming ack (size=4), or live_frame_refresh()
             * never succeeded so g_live_frame_sz is 0. Not a real frame
             * header: don't start tracking. Still clear any stale tracking
             * state for this fd (in case it was previously mid-frame),
             * matching the file's fail-open convention. */
            live_stream_end(fd);
        }
        return real(fd, buf, count);
    }
    int live_idx = live_stream_find(fd);
    if (live_idx >= 0) {
        size_t off = live_stream_off[live_idx];
        if (g_live_frame && off + count <= g_live_frame_sz) {
            ssize_t wrote = real(fd, g_live_frame + off, count);
            if (wrote > 0) {
                live_stream_off[live_idx] += (size_t)wrote;
                if (live_stream_off[live_idx] >= g_live_frame_sz) live_stream_end(fd);
            }
            return wrote;
        }
        live_stream_end(fd);  /* size mismatch -- fail open, don't touch this call */
    }

    if (count > 0 && count < AF_SCRATCH_CAP) {
        char scratch[AF_SCRATCH_CAP + 32];
        size_t n = af_rewrite_if_fail(buf, count, scratch, sizeof(scratch));
        if (n) {
            fprintf(stderr, "[hwid_stub] AutoFocus fail/cancel -> complete (spoofed)\n");
            fflush(stderr);
            ssize_t wrote = real(fd, scratch, n);
            /* Report success against the ORIGINAL requested length so the
             * caller's own "did the whole message go out" bookkeeping stays
             * consistent, even though the actual buffer sent was longer. */
            return wrote == (ssize_t)n ? (ssize_t)count : wrote;
        }
    }
    return real(fd, buf, count);
}

ssize_t send(int fd, const void *buf, size_t count, int flags) {
    static ssize_t (*real)(int, const void *, size_t, int) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "send");
    observe_wheel_position(buf, count);
    if (count > 0 && count < AF_SCRATCH_CAP) {
        char scratch[AF_SCRATCH_CAP + 32];
        size_t n = af_rewrite_if_fail(buf, count, scratch, sizeof(scratch));
        if (n) {
            fprintf(stderr, "[hwid_stub] AutoFocus fail/cancel -> complete (spoofed)\n");
            fflush(stderr);
            ssize_t wrote = real(fd, scratch, n, flags);
            return wrote == (ssize_t)n ? (ssize_t)count : wrote;
        }
    }
    return real(fd, buf, count, flags);
}

/* close() intercept -- clears any live-stream tracking-table entry for this
 * fd before delegating to the real close(). Without this, a stream aborted
 * mid-frame (e.g. a client closing live view before the full payload is
 * written) leaves a stale live_stream_fd[]/live_stream_off[] entry keyed on
 * that fd integer. If the OS later reuses that same fd for an unrelated
 * connection (e.g. a new control-channel socket) before a new frame header
 * arrives on it, every write() on that unrelated fd would get silently
 * substituted with g_live_frame bytes at the stale offset -- reproduced
 * empirically as corruption of an unrelated get_verify_str JSON reply.
 * Calling live_stream_end() here (a no-op if fd isn't tracked) guarantees a
 * tracking entry can never survive past the fd's actual close. */
int close(int fd) {
    static int (*real)(int) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "close");
    live_stream_end(fd);
    return real(fd);
}

/* poll() / ppoll() intercept — log which fds the binary waits on after
 * STREAMON so we can identify the frame-delivery mechanism.  For any polled
 * fd that is a tracked camera fd, claim POLLIN immediately (the real poll on
 * /dev/null would return POLLHUP which the binary might treat as an error). */
int poll(struct pollfd *fds, nfds_t nfds, int timeout) {
    static int (*real)(struct pollfd *, nfds_t, int) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "poll");
    int has_cam = 0;
    for (nfds_t i = 0; i < nfds; i++) {
        if (cam_fd_is_tracked(fds[i].fd)) {
            has_cam = 1;
            if (cam_verbose()) {
                fprintf(stderr, "[hwid_stub] poll fd=%d events=0x%x (CAMERA) timeout=%d\n",
                        fds[i].fd, fds[i].events, timeout);
                fflush(stderr);
            }
        }
    }
    if (!has_cam) return real(fds, nfds, timeout);
    /* Call real poll so non-camera fds in the set are handled correctly.
     * Then for camera fds: override revents to POLLIN so the binary proceeds
     * to DQBUF rather than treating POLLHUP (/dev/null EOF) as an error. */
    int ret = real(fds, nfds, timeout);
    for (nfds_t i = 0; i < nfds; i++) {
        if (cam_fd_is_tracked(fds[i].fd)) {
            fds[i].revents = POLLIN;
            if (cam_verbose()) {
                fprintf(stderr, "[hwid_stub] poll cam fd=%d → forcing POLLIN (was 0x%x)\n",
                        fds[i].fd, fds[i].revents);
                fflush(stderr);
            }
            if (ret == 0) ret = 1;
        }
    }
    return ret;
}

/* ppoll() — same as poll() but with timespec timeout and optional sigmask */
int ppoll(struct pollfd *fds, nfds_t nfds, const struct timespec *tmo,
          const sigset_t *sigmask) {
    static int (*real)(struct pollfd *, nfds_t, const struct timespec *,
                       const sigset_t *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "ppoll");
    int has_cam = 0;
    for (nfds_t i = 0; i < nfds; i++) {
        if (cam_fd_is_tracked(fds[i].fd)) {
            has_cam = 1;
            if (cam_verbose()) {
                fprintf(stderr, "[hwid_stub] ppoll fd=%d events=0x%x (CAMERA)\n",
                        fds[i].fd, fds[i].events);
                fflush(stderr);
            }
        }
    }
    if (!has_cam) return real(fds, nfds, tmo, sigmask);
    int ret = real(fds, nfds, tmo, sigmask);
    for (nfds_t i = 0; i < nfds; i++) {
        if (cam_fd_is_tracked(fds[i].fd)) {
            fds[i].revents = POLLIN;
            if (ret == 0) ret = 1;
        }
    }
    return ret;
}

/* select() intercept — log if the camera fd is in readfds, override to ready */
int select(int nfds, fd_set *readfds, fd_set *writefds,
           fd_set *exceptfds, struct timeval *timeout) {
    static int (*real)(int, fd_set *, fd_set *, fd_set *, struct timeval *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "select");
    int has_cam = 0;
    if (readfds) {
        for (int i = 0; i < cam_fd_count; i++) {
            if (cam_fds[i] >= 0 && cam_fds[i] < nfds && FD_ISSET(cam_fds[i], readfds)) {
                has_cam = 1;
                if (cam_verbose()) {
                    fprintf(stderr, "[hwid_stub] select nfds=%d cam fd=%d in readfds timeout=%ldms\n",
                            nfds, cam_fds[i],
                            timeout ? (long)(timeout->tv_sec * 1000 + timeout->tv_usec / 1000) : -1L);
                    fflush(stderr);
                }
            }
        }
    }
    if (!has_cam) return real(nfds, readfds, writefds, exceptfds, timeout);
    int ret = real(nfds, readfds, writefds, exceptfds, timeout);
    if (readfds) {
        for (int i = 0; i < cam_fd_count; i++) {
            if (cam_fds[i] >= 0 && cam_fds[i] < nfds) {
                FD_SET(cam_fds[i], readfds);
                if (ret == 0) ret = 1;
            }
        }
    }
    return ret;
}
