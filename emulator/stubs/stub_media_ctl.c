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
    .info_model  = "rkcif_mipi_lvds",
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

void *media_device_new(const char *devnode) {
    fprintf(stderr, "[media_ctl] media_device_new(%s)\n", devnode ? devnode : "(null)");
    fflush(stderr);
    if (!devnode) return NULL;
    if (strstr(devnode, "media0")) return &_rkispp_dev;
    if (strstr(devnode, "media1")) return &_rkcif_dev;
    return NULL;  /* media2+ are not exposed via access() */
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
    if (strstr(name, "stream_cif_mipi_id")) return (void *)&_cif_entity;
    return NULL;
}

/* Called by the binary with ONE argument (entity ptr); returns pointer to
 * the entity descriptor struct on success, NULL to skip this entity.
 * The binary then reads: *(ret+36) for type, *(ret+4) for name. */
void *media_entity_get_info(void *entity) {
    fprintf(stderr, "[media_ctl] media_entity_get_info(entity=%p)\n", entity);
    fflush(stderr);
    if (entity == (void *)&_sensor_entity)
        return &_sensor_desc;
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
