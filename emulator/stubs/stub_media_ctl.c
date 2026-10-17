/*
 * Fake Rockchip RV1126 libmedia-ctl for ASICAM_Open camera graph setup.
 *
 * zwoair_imager expects to find two media devices:
 *   /dev/media0  →  model "rkispp0"       (ISP post-processor)
 *   /dev/media1  →  model "rkcif_mipi_lvds" (MIPI CIF capture input)
 *
 * Struct layout (derived from disassembly): the binary reads media_device+28
 * as the model name C-string.  With the Rockchip libmedia-ctl layout:
 *   { char *devnode [4], int fd [4], int extra [4],
 *     struct media_device_info { char driver[16], char model[32], ... } }
 * info.model starts at offset 28 (4+4+4+16 = 28). ← key constraint
 *
 * media_entity_get_info is called by the binary with ONE argument (entity
 * pointer) and must return a non-NULL pointer to a media_entity_desc-like
 * struct with:
 *   offset  4: entity name (char[32]), must start with "m00" for S50
 *   offset 36: entity type (uint32_t) = 0x00020001 (MEDIA_ENT_F_CAM_SENSOR)
 *
 * Counter logic in ASICAM_Open — must reach 3 for success (return 0):
 *   +1  rkispp_m_bypass entity devname  → output_buf[  0..63]  (YUV dev)
 *   +1  stream_cif_mipi_id0 devname     → output_buf[ 64..127] (RAW dev)
 *   +1  sensor entity devname           → output_buf[128..191] (CTRL dev)
 *       sensor entity name              → output_buf[192..255] (Sensor)
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Fake media_device struct.  info_model is at offset 28 = device+28,
 * which is what the binary's strcmp probes to identify the pipeline type. */
struct fake_media_dev {
    char    *devnode;          /* offset  0 : pointer (4 bytes) */
    int      fd;               /* offset  4 : 4 bytes           */
    int      extra;            /* offset  8 : Rockchip-extra 4B */
    char     info_driver[16];  /* offset 12 : info.driver       */
    char     info_model[32];   /* offset 28 : info.model ← KEY  */
    char     info_rest[512];   /* padding — remaining info + entities fields */
};

static struct fake_media_dev _rkispp_dev = {
    .info_driver = "rkispp",
    .info_model  = "rkispp0",
};

static struct fake_media_dev _rkcif_dev = {
    .info_driver = "rkcif",
#ifdef __aarch64__
    .info_model  = "rkcif-mipi-lvds",
#else
    .info_model  = "rkcif_mipi_lvds",
#endif
};

/* Three distinct entity handles so media_entity_get_devname can dispatch. */
static int _rkispp_entity;   /* rkispp_m_bypass   → /dev/video4    */
static int _cif_entity;      /* stream_cif_mipi_id0 → /dev/video0  */
static int _sensor_entity;   /* IMX462 sensor     → /dev/v4l-subdev0 */

/* Fake sensor entity descriptor returned by media_entity_get_info().
 * S50 entity-scan loop checks: type==0x00020001 AND name[0:3]=="m00". */
static struct {
    uint32_t id;       /* offset  0 */
    char     name[32]; /* offset  4 : must start with "m00" for S50 */
    uint32_t type;     /* offset 36 : MEDIA_ENT_F_CAM_SENSOR = 0x00020001 */
} _sensor_desc = {
    .id   = 1,
    .name = "m00_b_imx462 1-001a",
    .type = 0x00020001,
};

#ifdef __aarch64__
/* The aarch64 (RV1126B, S30 Pro / S50 Pro) libasisdk scans media0/2/4 for
 * camera 0 (index starts at the camera number and steps by 2) and needs
 * three hits for get_v4l2_devs_info() to succeed:
 *   media0 "rkvpss0"          entity rkvpss_scale0       -> YUV device
 *   media2 "rkcif-mipi-lvds"  entity stream_cif_mipi_id0 -> RAW device
 *                              + an "m00_..." sensor entity -> control device
 * media4 only has to exist (any model that matches nothing, no entities).
 * Odd indices (camera 1) have no sensor: media_device_new() returns NULL. */
static struct fake_media_dev _rkvpss_dev = {
    .info_driver = "rkvpss",
    .info_model  = "rkvpss0",
};
static struct fake_media_dev _rkisp_dev = {
    .info_driver = "rkisp",
    .info_model  = "rkisp0",
};

/* Sensor name follows SEESTAR_MODEL, same table as stub_hwid.c's
 * camera_sensor_name(); the Pro models this build serves use imx585. */
static const char *sensor_name(void) {
    const char *m = getenv("SEESTAR_MODEL");
    if (m && strcmp(m, "S30") == 0) return "imx662";
    if (m && strcmp(m, "S50V2") == 0) return "imx662";
    return "imx585";
}
#else
static const char *sensor_name(void) { return "imx462"; }
#endif

void *media_device_new(const char *devnode) {
    fprintf(stderr, "[media_ctl] media_device_new(%s)\n", devnode ? devnode : "(null)");
    fflush(stderr);
    if (!devnode) return NULL;
#ifdef __aarch64__
    if (strcmp(devnode, "/dev/media0") == 0) return &_rkvpss_dev;
    if (strcmp(devnode, "/dev/media2") == 0) return &_rkcif_dev;
    if (strcmp(devnode, "/dev/media4") == 0) return &_rkisp_dev;
    return NULL;
#else
    if (strstr(devnode, "media0")) return &_rkispp_dev;
    if (strstr(devnode, "media1")) return &_rkcif_dev;
    return NULL;  /* media2+ are not exposed via access() */
#endif
}

int media_device_enumerate(void *media) {
    /* Return 0 = success.  The binary: cmp r0,#0; bne → error-return path.
     * The previous session incorrectly returned 1 here; that caused the
     * function to immediately return 1 to ASICAM_Open as an error code
     * (−988 "open video source device failed"). */
    fprintf(stderr, "[media_ctl] media_device_enumerate -> 0 (success)\n");
    fflush(stderr);
    return 0;
}

void media_device_unref(void *media) {
    fprintf(stderr, "[media_ctl] media_device_unref\n");
    fflush(stderr);
}

int media_get_entities_count(void *media) {
    /* Only the rkcif device participates in the sensor-entity scan. */
    int count = (media == (void *)&_rkcif_dev) ? 1 : 0;
    fprintf(stderr, "[media_ctl] media_get_entities_count -> %d\n", count);
    fflush(stderr);
    return count;
}

void *media_get_entity(void *media, int idx) {
    fprintf(stderr, "[media_ctl] media_get_entity(idx=%d)\n", idx);
    fflush(stderr);
    return (idx == 0) ? (void *)&_sensor_entity : NULL;
}

void *media_get_entity_by_name(void *media, const char *name, int len) {
    const char *n = name ? name : "";
    int plen = (len > 0 && len < 128) ? len : (int)strlen(n);
    fprintf(stderr, "[media_ctl] media_get_entity_by_name(%.*s)\n", plen, n);
    fflush(stderr);
    if (!name) return NULL;
    if (strstr(name, "rkispp_m_bypass"))    return (void *)&_rkispp_entity;
    if (strstr(name, "rkvpss_scale0"))      return (void *)&_rkispp_entity;
    if (strstr(name, "stream_cif_mipi_id")) return (void *)&_cif_entity;
    return NULL;
}

/* Called by the binary with ONE argument (entity ptr); returns pointer to
 * the entity descriptor struct on success, NULL to skip this entity.
 * The binary then reads: *(ret+36) for type, *(ret+4) for name. */
void *media_entity_get_info(void *entity) {
    fprintf(stderr, "[media_ctl] media_entity_get_info(entity=%p)\n", entity);
    fflush(stderr);
    if (entity == (void *)&_sensor_entity) {
        snprintf(_sensor_desc.name, sizeof(_sensor_desc.name),
                 "m00_b_%s 1-001a", sensor_name());
        return &_sensor_desc;
    }
    return NULL;
}

const char *media_entity_get_devname(void *entity) {
    const char *devname;
    if      (entity == (void *)&_rkispp_entity)  devname = "/dev/video4";
    else if (entity == (void *)&_cif_entity)     devname = "/dev/video0";
    else if (entity == (void *)&_sensor_entity)  devname = "/dev/v4l-subdev0";
    else                                          devname = "/dev/video2";
    fprintf(stderr, "[media_ctl] media_entity_get_devname(%p) -> %s\n", entity, devname);
    fflush(stderr);
    return devname;
}
