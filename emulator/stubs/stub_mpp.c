/*
 * Stub for librockchip_mpp.so.1
 *
 * Satisfies the 32 RK_MPI_* symbols and 22 mpp_* symbols zwoair_imager
 * imports from this library.  All hardware operations return success (0) or a
 * NULL handle.  RK_MPI_SYS_Init is the critical startup gate — must return 0.
 *
 * mpp_create returns a real MppApi vtable so the binary can safely call
 * mpi->encode_put_frame / mpi->encode_get_packet without dereferencing NULL.
 * encode_get_packet always returns *packet=NULL, causing the binary to log
 * "mpp encode get packet failed" and skip the frame, rather than crashing.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define LOG(...) do { fprintf(stderr, "[mpp] " __VA_ARGS__); fflush(stderr); } while(0)

/* ── MppApi vtable ──────────────────────────────────────────────────────── */

static int mpp_noop(void) { return 0; }
static int mpp_encode_put_frame(void *ctx, void *frame) { (void)ctx; (void)frame; return 0; }
static int mpp_encode_get_packet(void *ctx, void **pkt) {
    (void)ctx;
    if (pkt) *pkt = NULL;   /* no encoded data available — caller handles gracefully */
    return 0;
}

/* MppApi layout (Rockchip MPP v1, ARM32 — 4-byte pointers):
 *   [0] uint32_t size     offset 0
 *   [1] uint32_t version  offset 4
 *   fn[0..13]             offset 8..60 (14 function pointers × 4 bytes)
 *   decode_put_packet  [fn0]  offset 8
 *   decode_get_frame   [fn1]  offset 12
 *   encode_put_frame   [fn2]  offset 16
 *   encode_get_packet  [fn3]  offset 20
 *   isp_put_frame      [fn4]  offset 24
 *   isp_get_packet     [fn5]  offset 28
 *   poll               [fn6]  offset 32
 *   dequeue            [fn7]  offset 36
 *   enqueue            [fn8]  offset 40
 *   reset              [fn9]  offset 44
 *   control            [fn10] offset 48
 *   decode (async)     [fn11] offset 52
 *   encode (async)     [fn12] offset 56
 *   isp    (async)     [fn13] offset 60
 */
typedef struct {
    uint32_t size;
    uint32_t version;
    void *fn[14];
} FakeMppApi;

static FakeMppApi fake_mpp_api = {
    .size    = 64,
    .version = 1,
    .fn = {
        (void*)mpp_noop,              /* decode_put_packet */
        (void*)mpp_noop,              /* decode_get_frame  */
        (void*)mpp_encode_put_frame,  /* encode_put_frame  */
        (void*)mpp_encode_get_packet, /* encode_get_packet */
        (void*)mpp_noop,              /* isp_put_frame     */
        (void*)mpp_noop,              /* isp_get_packet    */
        (void*)mpp_noop,              /* poll              */
        (void*)mpp_noop,              /* dequeue           */
        (void*)mpp_noop,              /* enqueue           */
        (void*)mpp_noop,              /* reset             */
        (void*)mpp_noop,              /* control           */
        (void*)mpp_noop,              /* decode (async)    */
        (void*)mpp_noop,              /* encode (async)    */
        (void*)mpp_noop,              /* isp (async)       */
    }
};

static int fake_mpp_ctx;

/* ── Low-level mpp_* API ────────────────────────────────────────────────── */

int mpp_create(void **ctx, void **mpi) {
    LOG("mpp_create ctx=%p mpi=%p\n", (void*)ctx, (void*)mpi);
    if (ctx) *ctx = &fake_mpp_ctx;
    if (mpi) *mpi = &fake_mpp_api;
    return 0;
}
int mpp_destroy(void *ctx) {
    LOG("mpp_destroy ctx=%p\n", ctx);
    return 0;
}
int mpp_init(void *ctx, int type, int coding) {
    LOG("mpp_init ctx=%p type=%d coding=%d\n", ctx, type, coding);
    return 0;
}

/* Frame lifecycle */
static int fake_frame_sentinel;
int mpp_frame_init(void **frame) {
    if (frame) *frame = &fake_frame_sentinel;
    return 0;
}
int mpp_frame_deinit(void **frame) {
    if (frame) *frame = NULL;
    return 0;
}
int mpp_frame_set_buffer(void *frame, void *buf)      { (void)frame; (void)buf;    return 0; }
int mpp_frame_set_eos(void *frame, uint32_t eos)      { (void)frame; (void)eos;    return 0; }
int mpp_frame_set_fmt(void *frame, uint32_t fmt)      { (void)frame; (void)fmt;    return 0; }
int mpp_frame_set_height(void *frame, uint32_t h)     { (void)frame; (void)h;      return 0; }
int mpp_frame_set_width(void *frame, uint32_t w)      { (void)frame; (void)w;      return 0; }
int mpp_frame_set_hor_stride(void *frame, uint32_t s) { (void)frame; (void)s;      return 0; }
int mpp_frame_set_ver_stride(void *frame, uint32_t s) { (void)frame; (void)s;      return 0; }

/* Packet lifecycle */
int mpp_packet_deinit(void **pkt) {
    if (pkt) *pkt = NULL;
    return 0;
}
int mpp_packet_get_eos(void *pkt)     { (void)pkt; return 1; }   /* signal EOS → binary skips */
uint64_t mpp_packet_get_length(void *pkt) { (void)pkt; return 0; }
void *mpp_packet_get_pos(void *pkt)   { (void)pkt; return NULL; }
void *mpp_packet_get_meta(void *pkt)  { (void)pkt; return NULL; }
int mpp_packet_has_meta(void *pkt)    { (void)pkt; return 0; }

/* Meta */
int mpp_meta_get_s32(void *meta, uint32_t key, int *val) {
    (void)meta; (void)key;
    if (val) *val = 0;
    return -1; /* not found */
}

/* Buffer */
void *mpp_buffer_get_ptr_with_caller(void *buf, const char *caller, int line) {
    (void)buf; (void)caller; (void)line;
    return NULL;
}
int mpp_buffer_get_with_tag(void *grp, void **buf, size_t size,
                             const char *tag, const char *caller) {
    (void)grp; (void)size; (void)tag; (void)caller;
    if (buf) *buf = NULL;
    return -1; /* fail → binary falls back gracefully */
}
int mpp_buffer_put_with_caller(void *buf, const char *caller) {
    (void)buf; (void)caller;
    return 0;
}

/* System */
int RK_MPI_SYS_Init(void)                                          { return 0; }
int RK_MPI_SYS_Bind(void *src, void *dst)                          { return 0; }
int RK_MPI_SYS_UnBind(void *src, void *dst)                        { return 0; }
int RK_MPI_SYS_RegisterOutCb(void *chn, void *cb)                  { return 0; }
int RK_MPI_SYS_SendMediaBuffer(int mod, int chn, void *mb)         { return 0; }
int RK_MPI_SYS_StopGetMediaBuffer(int mod, int chn)                { return 0; }
void *RK_MPI_SYS_GetMediaBuffer(int mod, int chn, int ms)          { return NULL; }

/* Media Buffer */
void *RK_MPI_MB_CreateImageBuffer(void *info, int dma, int flags)  { return NULL; }
int RK_MPI_MB_ReleaseBuffer(void *mb)                              { return 0; }
int RK_MPI_MB_GetChannelID(void *mb)                               { return 0; }
int RK_MPI_MB_GetFlag(void *mb)                                    { return 0; }
int RK_MPI_MB_GetSize(void *mb)                                    { return 0; }
int RK_MPI_MB_SetSize(void *mb, int size)                          { return 0; }
uint64_t RK_MPI_MB_GetTimestamp(void *mb)                          { return 0; }
int RK_MPI_MB_SetTimestamp(void *mb, uint64_t ts)                  { return 0; }
void *RK_MPI_MB_GetPtr(void *mb)                                   { return NULL; }

/* RGA (2D Graphics Acceleration) */
int RK_MPI_RGA_CreateChn(int chn, void *attr)                      { return 0; }
int RK_MPI_RGA_DestroyChn(int chn)                                 { return 0; }
int RK_MPI_RGA_GetChnAttr(int chn, void *attr)                     { return 0; }
int RK_MPI_RGA_SetChnAttr(int chn, void *attr)                     { return 0; }

/* Video Encode */
int RK_MPI_VENC_CreateChn(int chn, void *attr)                     { return 0; }
int RK_MPI_VENC_DestroyChn(int chn)                                { return 0; }
int RK_MPI_VENC_GetRcParam(int chn, void *param)                   { return 0; }
int RK_MPI_VENC_SetRcParam(int chn, void *param)                   { return 0; }
int RK_MPI_VENC_SetGop(int chn, int gop)                           { return 0; }
int RK_MPI_VENC_SetRotation(int chn, int rot)                      { return 0; }

/* Video Input */
int RK_MPI_VI_SetChnAttr(int pipe, int chn, void *attr)            { return 0; }
int RK_MPI_VI_EnableChn(int pipe, int chn)                         { return 0; }
int RK_MPI_VI_DisableChn(int pipe, int chn)                        { return 0; }
int RK_MPI_VI_StartChn(int pipe, int chn)                          { return 0; }
int RK_MPI_VI_StopChn(int pipe, int chn)                           { return 0; }
int RK_MPI_VI_StartStream(int pipe, int chn)                       { return 0; }
