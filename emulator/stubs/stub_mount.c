/*
 * mount_stub: TCP stub server for port 4400 (Seestar mount/motor controller).
 *
 * zwoair_imager connects OUT to 127.0.0.1:4400 and sends JSON-RPC commands to
 * the mount controller daemon.  Without something listening here every scope
 * command proxied through the binary returns code:103 (method not found).
 *
 * Protocol: newline-delimited JSON (messages end with \r\n).
 * Commands handled (formats verified against real device via nc 127.0.0.1 4400):
 *   test_connection      → result:"server connected!"
 *   scope_get_mode       → result:"eq"
 *   scope_is_moving      → result:"none"
 *   scope_get_axle_coord → result:[-90.0,0.0]
 *   scope_get_equ_coord  → result:{"ra":0.0,"dec":0.0}
 *   scope_get_track_state→ result:false, track_error:"", track_code:0
 *   scope_send_cmd       → result:0
 *   can_goto             → result:true  (firmware reads a falsey/absent value
 *                           as "mount can't goto" and aborts the goto)
 *   scope_get_cap        → result:{"goto":true,"track":true}  (see GOTO note)
 *   scope_goto [ra,dec]  → result:0, then snaps sim pointing to target and
 *                           pushes a ScopeGoto "complete" Event (see GOTO note)
 *   scope_get_ra_dec     → result:[ra_hours,dec_deg,0] (3-elem array; scalar gave
 *                           "operation fail" in the goto RA-flip check)
 *   scope_move_left/right_by_angle → result:0, step pointing on RA + push a
 *                           "MoveByAngle" complete Event (eq_3p 3PPA moves)
 *   scope_park           → result:0, then pushes a ScopeHome "complete" Event
 *                           (same keyed-by-"Event" mechanism; seestar_alp's
 *                           shut_down_thread sends scope_park before
 *                           pi_shutdown/pi_reboot and blocks in wait_end_op
 *                           with NO TIMEOUT until ScopeHome reaches a terminal
 *                           state, so without this push shutdown/reboot would
 *                           hang forever. A pre-3PPA scope_park briefly existed
 *                           on the front_v2 branch too, which is how this gap
 *                           was found, but was reverted there as unneeded on
 *                           main — shut_down_thread is the real, main-line
 *                           caller this handles.)
 * All responses include jsonrpc:"2.0", method echo, code:0, and echoed id.
 *
 * GOTO (reverse-engineered from the binary, v3.1.2) — WORKS end-to-end. Gates:
 *  1. can_goto must be truthy.
 *  2. scope_get_cap: the firmware's capability check (VA 0xd7a4c) does NOT parse
 *     result as a number — it runs response.find("goto") on the whole response
 *     text (needle "goto" at .rodata 0x67dfa8). Present → CanGoto; absent → it
 *     logs [CannotGoto]error, not support goto and bails before AutoGoto.
 *  3. scope_goto runs CLOSED-LOOP: the firmware waits for a pushed ScopeGoto Event
 *     (WaitGoto, fn 0xdaf58, keys mount msgs by "Event", strstr's for
 *     "complete"/"fail"/"cancel"), then exposes + PLATE-SOLVES and only converges
 *     when the SOLVED position ≈ target. So scope_goto snaps the sim pointing to
 *     the target (write_pointing_target) so the host renderd re-renders solve.fits
 *     there, AND pushes ScopeGoto complete.
 *  4. The goto readout's RA-flip/calibration check needs valid mount calibration
 *     (set by 3PPA — which needs the MoveByAngle handling above) and a parseable
 *     scope_get_ra_dec, else "cannot check calibration flip".
 *
 * REQUIRES: sim/renderd.py on the host watching sim/shared/pointing.json; a client
 * heartbeat during 3PPA/goto (firmware drops idle sockets after ~16s); and 3PPA
 * run once to establish calibration before Goto Target.
 *
 * KNOWN LIMITATION: the firmware reads the plate solve ~0.14-0.34 deg off target
 * (a coordinate transform from the sim's spurious ~0.15 deg 3PPA pa_error, NOT a
 * render/solve error — isolated solve is accurate to <2 arcsec). This is not a
 * fixed pixel offset so render compensation can't fix it; instead the sandbox
 * raises autogoto_threshold to 0.5 deg (ASIAIR_imager.xml) so the on-target goto
 * converges. Full analysis in the project_sandbox_goto memo.
 *
 * Compile (via Makefile): gcc -O0 -Wall -o mount_stub stub_mount.c
 * Launch from entrypoint.sh before exec'ing zwoair_imager.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <signal.h>
#include <sys/wait.h>
#include <time.h>

#define PORT     4400
#define BUF_SIZE 4096

static long extract_id(const char *json) {
    const char *p = strstr(json, "\"id\":");
    if (!p) return -1;
    p += 5;
    while (*p == ' ') p++;
    return strtol(p, NULL, 10);
}

#define POINTING_PATH "/run/seestar-sim/pointing.json"

static void read_pointing(double *ra_h, double *dec_d, double *ax0, double *ax1) {
    *ra_h = 0.0; *dec_d = 0.0; *ax0 = -90.0; *ax1 = 0.0;
    FILE *f = fopen(POINTING_PATH, "r");
    if (!f) return;
    char b[512]; size_t n = fread(b, 1, sizeof(b)-1, f); b[n]='\0'; fclose(f);
    char *p;
    if ((p=strstr(b,"\"ra_hours\":"))) *ra_h  = strtod(p+11, NULL);
    if ((p=strstr(b,"\"dec_deg\":")))  *dec_d = strtod(p+10, NULL);
    if ((p=strstr(b,"\"axle0\":")))    *ax0   = strtod(p+8,  NULL);
    if ((p=strstr(b,"\"axle1\":")))    *ax1   = strtod(p+8,  NULL);
}

/* Snap the simulated pointing to (ra_hours, dec_deg) so the plate-solve sim
 * renders the sky at the goto target. Matches sim/pointing.py's shape exactly
 * (ra_hours, dec_deg, axle0=ra*15, axle1=dec, seq, ts) and bumps seq so the
 * host renderd re-renders solve.fits; written atomically via tmp+rename so
 * renderd never observes a partial file. Keeping scope_get_equ_coord's source
 * (this same file) in sync means the mount also reports the target afterward. */
static void write_pointing_target(double ra_h, double dec_d) {
    long seq = 0;
    FILE *cf = fopen(POINTING_PATH, "r");
    if (cf) {
        char b[512]; size_t n = fread(b, 1, sizeof(b)-1, cf); b[n]='\0'; fclose(cf);
        char *p = strstr(b, "\"seq\":");
        if (p) seq = strtol(p + 6, NULL, 10);
    }
    const char *tmp = "/run/seestar-sim/pointing.json.tmp";
    FILE *f = fopen(tmp, "w");
    if (!f) return;
    fprintf(f, "{\"ra_hours\": %.6f, \"dec_deg\": %.6f, \"axle0\": %.6f, "
               "\"axle1\": %.6f, \"seq\": %ld, \"ts\": %ld.0}",
            ra_h, dec_d, ra_h * 15.0, dec_d, seq + 1, (long)time(NULL));
    fclose(f);
    rename(tmp, POINTING_PATH);
}

/* Step the simulated pointing by a relative angle on the RA axis (hour angle),
 * keeping dec fixed. Used by the eq_3p polar-align move-by-angle commands so the
 * three 3PPA measurement points fall on distinct sky positions (a well-polar-
 * aligned mount moves purely in RA). delta_ra_deg is the commanded angle in
 * degrees; RA hours = degrees / 15. */
static void move_pointing_by_ra_deg(double delta_ra_deg) {
    double ra_h, dec_d, a0, a1;
    read_pointing(&ra_h, &dec_d, &a0, &a1);
    ra_h += delta_ra_deg / 15.0;
    while (ra_h < 0.0)  ra_h += 24.0;
    while (ra_h >= 24.0) ra_h -= 24.0;
    write_pointing_target(ra_h, dec_d);
}

static void extract_method(const char *json, char *out, int maxlen) {
    const char *p = strstr(json, "\"method\":");
    out[0] = '\0';
    if (!p) return;
    p += 9;
    while (*p == ' ' || *p == '\t') p++;
    if (*p != '"') return;
    p++;
    const char *e = strchr(p, '"');
    if (!e) return;
    int len = (int)(e - p);
    if (len >= maxlen) len = maxlen - 1;
    memcpy(out, p, len);
    out[len] = '\0';
}

static void handle_client(int fd) {
    char buf[BUF_SIZE];
    char line[BUF_SIZE];
    int pos = 0;
    ssize_t n;

    while ((n = read(fd, buf, sizeof(buf))) > 0) {
        for (int i = 0; i < n; i++) {
            char c = buf[i];
            if (c == '\n') {
                line[pos] = '\0';
                if (pos > 0 && line[pos-1] == '\r') line[--pos] = '\0';
                pos = 0;
                if (line[0] == '\0') continue;

                long id = extract_id(line);
                char method[64];
                extract_method(line, method, sizeof(method));
                fprintf(stderr, "[mount_stub] RAW id=%ld method=%s line=%.200s\n",
                        id, method[0] ? method : "?", line);
                fflush(stderr);

/* Real device response formats (verified via ssh pi@seestar.local):
 *   test_connection:     result:"server connected!"
 *   scope_get_mode:      result:"eq"
 *   scope_is_moving:     result:"none"
 *   scope_get_axle_coord:result:[-90.0,0.0]   (array: [axis0,axis1])
 *   scope_get_equ_coord: result:{"ra":N,"dec":N}
 *   scope_get_track_state:result:false, track_error:"...", track_code:N
 *   scope_send_cmd:      result:0
 * All responses include jsonrpc:"2.0" and the method echo. */
#define JRPC "{\"jsonrpc\":\"2.0\",\"Timestamp\":\"0.0\","
                char resp[512];
                if (strcmp(method, "test_connection") == 0) {
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":\"server connected!\",\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                } else if (strcmp(method, "scope_get_mode") == 0) {
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":\"eq\",\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                } else if (strcmp(method, "scope_is_moving") == 0) {
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":\"none\",\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                } else if (strcmp(method, "scope_get_axle_coord") == 0) {
                    double ra,dec,a0,a1; read_pointing(&ra,&dec,&a0,&a1);
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":[%.6f,%.6f],\"code\":0,\"id\":%ld}\r\n",
                        method, a0, a1, id);
                } else if (strcmp(method, "scope_get_equ_coord") == 0) {
                    double ra,dec,a0,a1; read_pointing(&ra,&dec,&a0,&a1);
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":{\"ra\":%.6f,\"dec\":%.6f},\"code\":0,\"id\":%ld}\r\n",
                        method, ra, dec, id);
                } else if (strcmp(method, "scope_get_ra_dec") == 0) {
                    /* Distinct from scope_get_equ_coord: the firmware's
                     * GetRADecDegree parses result as a THREE-element ARRAY
                     * (regex result":[(.*),(.*),(.*)], logged "mount ra/dec h/d")
                     * — [ra_hours, dec_deg, X] — and errors ("args is all 0") if
                     * all are zero. It's queried by the goto's "check RA flip" /
                     * "get final ra/dec" step; returning result:0 (the old
                     * default) made that step fail ("cannot check calibration
                     * flip") so every goto aborted. Report the current pointing
                     * (mount's electronic RA/Dec) so the flip check can compare
                     * it against the plate-solve. Third element left 0. */
                    double ra,dec,a0,a1; read_pointing(&ra,&dec,&a0,&a1);
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":[%.6f,%.6f,0],\"code\":0,\"id\":%ld}\r\n",
                        method, ra, dec, id);
                } else if (strcmp(method, "scope_get_track_state") == 0) {
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":false,\"code\":0,\"track_error\":\"\",\"track_code\":0,\"id\":%ld}\r\n",
                        method, id);
                } else if (strcmp(method, "scope_send_cmd") == 0) {
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":0,\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                } else if (strcmp(method, "can_goto") == 0) {
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":true,\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                } else if (strcmp(method, "scope_get_cap") == 0) {
                    /* The firmware's goto gate does NOT parse result as a
                     * number — it takes the whole response as a string and
                     * does response.find("goto") (check at binary VA 0xd7a4c,
                     * needle "goto" at 0x67dfa8). Present → CanGoto; absent →
                     * [CannotGoto]error, not support goto. So the result MUST
                     * contain the literal substring "goto". A capability object
                     * satisfies both the substring check and the real device's
                     * shape. */
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":{\"goto\":true,\"track\":true},\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                } else if (strcmp(method, "scope_goto") == 0) {
                    /* Goto completion in the firmware is CLOSED-LOOP: after the
                     * mount reports arrival, it exposes a frame, plate-solves it,
                     * and only converges when the SOLVED position matches the
                     * target. So two things must happen here:
                     *  1. Snap the sim pointing to the target so the host renderd
                     *     re-renders solve.fits at the target → the firmware's
                     *     plate solve returns the target → AutoGoto converges.
                     *  2. Push a ScopeGoto "complete" Event so WaitGoto (firmware
                     *     fn 0xdaf58) unblocks: it keys mount messages by their
                     *     "Event" field and strstr's the payload for "complete".
                     * params is [ra_hours, dec_deg]. */
                    double gra = 0.0, gdec = 0.0;
                    const char *pp = strstr(line, "\"params\":");
                    if (pp && (pp = strchr(pp, '['))) {
                        gra = strtod(pp + 1, NULL);
                        const char *comma = strchr(pp, ',');
                        if (comma) gdec = strtod(comma + 1, NULL);
                    }
                    write_pointing_target(gra, gdec);
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":0,\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                    write(fd, resp, strlen(resp));
                    fprintf(stderr, "[mount_stub] scope_goto [%.6f,%.6f] -> %s",
                            gra, gdec, resp);
                    char evt[256];
                    snprintf(evt, sizeof(evt),
                        "{\"Event\":\"ScopeGoto\",\"state\":\"complete\","
                        "\"cur_ra_dec\":[%.6f,%.6f],\"code\":0}\r\n", gra, gdec);
                    write(fd, evt, strlen(evt));
                    fprintf(stderr, "[mount_stub] push %s", evt);
                    fflush(stderr);
                    continue;  /* response + event already written */
                } else if (strcmp(method, "scope_park") == 0) {
                    /* shut_down_thread (device/seestar_device.py, on main)
                     * sends scope_park before pi_shutdown/pi_reboot, marks its
                     * local "ScopeHome" op state "working", and calls
                     * wait_end_op("ScopeHome") — a plain while-loop with NO
                     * TIMEOUT that only exits once a pushed Event named
                     * "ScopeHome" reaches state complete/fail/cancel (same
                     * keyed-by-"Event" mechanism as ScopeGoto/MoveByAngle).
                     * Without this push the ack alone leaves the firmware (and
                     * seestar_alp) waiting forever. */
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":0,\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                    write(fd, resp, strlen(resp));
                    fprintf(stderr, "[mount_stub] scope_park -> %s", resp);
                    const char *evt =
                        "{\"Event\":\"ScopeHome\",\"state\":\"complete\",\"code\":0}\r\n";
                    write(fd, evt, strlen(evt));
                    fprintf(stderr, "[mount_stub] push %s", evt);
                    fflush(stderr);
                    continue;  /* response + event already written */
                } else if (strcmp(method, "scope_move_left_by_angle") == 0 ||
                           strcmp(method, "scope_move_right_by_angle") == 0) {
                    /* eq_3p 3PPA moves the mount by a fixed angle between its
                     * three measurement points, then waits for a pushed
                     * "MoveByAngle" Event (same keyed-by-"Event" mechanism as
                     * ScopeGoto). Without it the firmware times out after 120s
                     * (ScopeMoveByAngle fail) and 3PPA aborts before points 2/3,
                     * so calibration is never established and later gotos fail
                     * the "check calibration flip" step.
                     * params is [angle_deg] (integer, may be negative). Step the
                     * sim pointing on the RA axis so the next plate-solve sees a
                     * distinct position, then ack + push the completion Event.
                     * "left" and "right" move opposite directions. */
                    double angle = 0.0;
                    const char *pp = strstr(line, "\"params\":");
                    if (pp && (pp = strchr(pp, '['))) angle = strtod(pp + 1, NULL);
                    double dir = (method[11] == 'r') ? -1.0 : 1.0;  /* left/right */
                    move_pointing_by_ra_deg(dir * angle);
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":0,\"code\":0,\"id\":%ld}\r\n",
                        method, id);
                    write(fd, resp, strlen(resp));
                    fprintf(stderr, "[mount_stub] %s [%.3f] -> %s", method, angle, resp);
                    const char *evt =
                        "{\"Event\":\"MoveByAngle\",\"state\":\"complete\",\"code\":0}\r\n";
                    write(fd, evt, strlen(evt));
                    fprintf(stderr, "[mount_stub] push %s", evt);
                    fflush(stderr);
                    continue;  /* response + event already written */
                } else {
                    snprintf(resp, sizeof(resp),
                        JRPC "\"method\":\"%s\",\"result\":0,\"code\":0,\"id\":%ld}\r\n",
                        method[0] ? method : "unknown", id >= 0 ? id : 0);
                }

                write(fd, resp, strlen(resp));
                fprintf(stderr, "[mount_stub] %s -> %s", method[0] ? method : "?", resp);
                fflush(stderr);
            } else {
                if (pos < (int)sizeof(line) - 1)
                    line[pos++] = c;
            }
        }
    }
}

static void reap_children(int sig) {
    (void)sig;
    while (waitpid(-1, NULL, WNOHANG) > 0);
}

int main(void) {
    int srv;
    struct sockaddr_in addr;

    signal(SIGCHLD, reap_children);

    srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) { perror("socket"); return 1; }

    int opt = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port        = htons(PORT);

    if (bind(srv, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        return 1;
    }
    if (listen(srv, 8) < 0) { perror("listen"); return 1; }

    fprintf(stderr, "[mount_stub] listening on 127.0.0.1:%d\n", PORT);
    fflush(stderr);

    for (;;) {
        int cli = accept(srv, NULL, NULL);
        if (cli < 0) continue;
        pid_t pid = fork();
        if (pid == 0) {
            close(srv);
            handle_client(cli);
            close(cli);
            exit(0);
        }
        close(cli);
    }
}
