/*
 * Stub for libeasymedia.so.1 (Rockchip EasyMedia / rkmedia)
 *
 * 166 RK_MPI_* symbols covering audio I/O, audio codecs, muxer, video mixing,
 * video output, and extended media buffer/sys APIs. All return 0 or NULL.
 * The overlapping SYS/VI/VENC/MB/RGA symbols are repeated here; the dynamic
 * linker resolves each symbol from whichever library it finds first
 * (librockchip_mpp.so.1 is listed first in NEEDED, so stub_mpp.c wins for
 * the 32 symbols it covers — these are here for completeness).
 *
 * Logging: the frame-delivery API calls are logged so we can see which path
 * the binary uses to receive processed frames from the ISP pipeline.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define LOG(...) do { fprintf(stderr, "[easymedia] " __VA_ARGS__); fflush(stderr); } while(0)

/* Audio Decode */
int RK_MPI_ADEC_CreateChn(int chn, void *attr)  { return 0; }
int RK_MPI_ADEC_DestroyChn(int chn)             { return 0; }

/* Audio Encode */
int RK_MPI_AENC_CreateChn(int chn, void *attr)  { return 0; }
int RK_MPI_AENC_DestroyChn(int chn)             { return 0; }
int RK_MPI_AENC_GetFd(int chn)                  { return -1; }
int RK_MPI_AENC_SetMute(int chn, int mute)      { return 0; }

/* Audio Input */
int RK_MPI_AI_SetChnAttr(int card, int chn, void *attr)          { return 0; }
int RK_MPI_AI_EnableChn(int card, int chn)                       { return 0; }
int RK_MPI_AI_DisableChn(int card, int chn)                      { return 0; }
int RK_MPI_AI_StartStream(int card, int chn)                     { return 0; }
int RK_MPI_AI_GetVolume(int card, int chn, int *vol)             { return 0; }
int RK_MPI_AI_SetVolume(int card, int chn, int vol)              { return 0; }
int RK_MPI_AI_EnableVqe(int card, int chn)                       { return 0; }
int RK_MPI_AI_DisableVqe(int card, int chn)                      { return 0; }
int RK_MPI_AI_GetRecordVqeAttr(int card, int chn, void *attr)    { return 0; }
int RK_MPI_AI_SetRecordVqeAttr(int card, int chn, void *attr)    { return 0; }
int RK_MPI_AI_GetTalkVqeAttr(int card, int chn, void *attr)      { return 0; }
int RK_MPI_AI_SetTalkVqeAttr(int card, int chn, void *attr)      { return 0; }

/* Audio Output */
int RK_MPI_AO_SetChnAttr(int card, int chn, void *attr)          { return 0; }
int RK_MPI_AO_EnableChn(int card, int chn)                       { return 0; }
int RK_MPI_AO_DisableChn(int card, int chn)                      { return 0; }
int RK_MPI_AO_ClearChnBuf(int card, int chn)                     { return 0; }
int RK_MPI_AO_GetVolume(int card, int chn, int *vol)             { return 0; }
int RK_MPI_AO_SetVolume(int card, int chn, int vol)              { return 0; }
int RK_MPI_AO_QueryChnStat(int card, int chn, void *stat)        { return 0; }
int RK_MPI_AO_EnableVqe(int card, int chn)                       { return 0; }
int RK_MPI_AO_DisableVqe(int card, int chn)                      { return 0; }
int RK_MPI_AO_GetVqeAttr(int card, int chn, void *attr)          { return 0; }
int RK_MPI_AO_SetVqeAttr(int card, int chn, void *attr)          { return 0; }

/* Motion / Object Detection */
int RK_MPI_ALGO_MD_CreateChn(int chn, void *attr)   { return 0; }
int RK_MPI_ALGO_MD_DestroyChn(int chn)              { return 0; }
int RK_MPI_ALGO_MD_EnableSwitch(int chn, int en)    { return 0; }
int RK_MPI_ALGO_MD_SetRegions(int chn, void *r)     { return 0; }
int RK_MPI_ALGO_OD_CreateChn(int chn, void *attr)   { return 0; }
int RK_MPI_ALGO_OD_DestroyChn(int chn)              { return 0; }
int RK_MPI_ALGO_OD_EnableSwitch(int chn, int en)    { return 0; }

/* Logging */
int RK_MPI_LOG_GetLevelConf(void *conf)             { return 0; }
int RK_MPI_LOG_SetLevelConf(void *conf)             { return 0; }

/* Media Buffer (extended set beyond stub_mpp.c) */
void *RK_MPI_MB_CreateImageBuffer(void *info, int dma, int flags)  { return NULL; }
void *RK_MPI_MB_CreateBuffer(int size, int dma, int flags)         { return NULL; }
void *RK_MPI_MB_CreateAudioBuffer(int size, int dma)               { return NULL; }
void *RK_MPI_MB_CreateAudioBufferExt(void *info, int dma, int f)   { return NULL; }
int RK_MPI_MB_ReleaseBuffer(void *mb)                              { return 0; }
int RK_MPI_MB_GetChannelID(void *mb)                               { return 0; }
int RK_MPI_MB_GetFlag(void *mb)                                    { return 0; }
int RK_MPI_MB_GetSize(void *mb)                                    { return 0; }
int RK_MPI_MB_SetSize(void *mb, int size)                          { return 0; }
uint64_t RK_MPI_MB_GetTimestamp(void *mb)                          { return 0; }
int RK_MPI_MB_SetTimestamp(void *mb, uint64_t ts)                  { return 0; }
void *RK_MPI_MB_GetPtr(void *mb)                                   { return NULL; }
int RK_MPI_MB_GetFD(void *mb)                                      { return -1; }
int RK_MPI_MB_GetDevFD(void *mb)                                   { return -1; }
int RK_MPI_MB_GetHandle(void *mb, void *hdl)                       { return 0; }
int RK_MPI_MB_GetModeID(void *mb)                                  { return 0; }
int RK_MPI_MB_GetTsvcLevel(void *mb)                               { return 0; }
int RK_MPI_MB_GetAudioInfo(void *mb, void *info)                   { return 0; }
int RK_MPI_MB_GetImageInfo(void *mb, void *info)                   { return 0; }
int RK_MPI_MB_IsViFrame(void *mb)                                  { return 0; }
int RK_MPI_MB_BeginCPUAccess(void *mb, int ro)                     { return 0; }
int RK_MPI_MB_EndCPUAccess(void *mb, int ro)                       { return 0; }
int RK_MPI_MB_Copy(void *dst, void *src, int sync)                 { return 0; }
int RK_MPI_MB_ConvertToImgBuffer(void *mb, void *info, int d)      { return 0; }
int RK_MPI_MB_ConvertToAudBuffer(void *mb, void *info, int d)      { return 0; }
int RK_MPI_MB_ConvertToAudBufferExt(void *mb, void *info, int d)   { return 0; }
int RK_MPI_MB_TsNodeDump(void *mb)                                 { return 0; }
void *RK_MPI_MB_POOL_Create(void *attr)                            { return NULL; }
int RK_MPI_MB_POOL_Destroy(void *pool)                             { return 0; }
void *RK_MPI_MB_POOL_GetBuffer(void *pool, int ms)                 { return NULL; }

/* Muxer */
int RK_MPI_MUXER_EnableChn(int chn, void *attr)                    { return 0; }
int RK_MPI_MUXER_DisableChn(int chn)                               { return 0; }
int RK_MPI_MUXER_Bind(void *src, void *dst)                        { return 0; }
int RK_MPI_MUXER_UnBind(void *src, void *dst)                      { return 0; }
int RK_MPI_MUXER_StreamStart(int chn)                              { return 0; }
int RK_MPI_MUXER_StreamStop(int chn)                               { return 0; }
int RK_MPI_MUXER_ManualSplit(int chn, void *attr)                  { return 0; }

/* RGA (2D Graphics Acceleration) */
int RK_MPI_RGA_CreateChn(int chn, void *attr)                      { return 0; }
int RK_MPI_RGA_DestroyChn(int chn)                                 { return 0; }
int RK_MPI_RGA_GetChnAttr(int chn, void *attr)                     { return 0; }
int RK_MPI_RGA_SetChnAttr(int chn, void *attr)                     { return 0; }
int RK_MPI_RGA_GetChnRegionLuma(int chn, void *r, void *l, int t)  { return 0; }
int RK_MPI_RGA_RGN_SetBitMap(int chn, void *r, void *bm)           { return 0; }
int RK_MPI_RGA_RGN_SetCover(int chn, void *r, void *c)             { return 0; }

/* System (extended) */
int RK_MPI_SYS_Init(void)                                          { LOG("SYS_Init\n"); return 0; }
int RK_MPI_SYS_Bind(void *src, void *dst)                          { LOG("SYS_Bind src=%p dst=%p\n", src, dst); return 0; }
int RK_MPI_SYS_UnBind(void *src, void *dst)                        { return 0; }
int RK_MPI_SYS_RegisterOutCb(void *chn, void *cb)                  { LOG("RegisterOutCb chn=%p cb=%p\n", chn, cb); return 0; }
int RK_MPI_SYS_RegisterOutCbEx(void *chn, void *cb, void *arg)     { LOG("RegisterOutCbEx chn=%p cb=%p arg=%p\n", chn, cb, arg); return 0; }
int RK_MPI_SYS_RegisterEventCb(void *chn, void *arg, void *cb)     { LOG("RegisterEventCb chn=%p cb=%p\n", chn, cb); return 0; }
int RK_MPI_SYS_SendMediaBuffer(int mod, int chn, void *mb)         { return 0; }
int RK_MPI_SYS_DevSendMediaBuffer(int mod, int chn, void *mb)      { return 0; }
int RK_MPI_SYS_StopGetMediaBuffer(int mod, int chn)                { LOG("StopGetMediaBuffer mod=%d chn=%d\n", mod, chn); return 0; }
int RK_MPI_SYS_StartGetMediaBuffer(int mod, int chn)               { LOG("StartGetMediaBuffer mod=%d chn=%d\n", mod, chn); return 0; }
void *RK_MPI_SYS_GetMediaBuffer(int mod, int chn, int ms)          { return NULL; }
int RK_MPI_SYS_SetFrameRate(int mod, int chn, int fps)             { return 0; }
int RK_MPI_SYS_SetMediaBufferDepth(int mod, int chn, int d)        { return 0; }
int RK_MPI_SYS_StartRecvFrame(int mod, int chn, void *attr)        { LOG("StartRecvFrame mod=%d chn=%d\n", mod, chn); return 0; }
int RK_MPI_SYS_DumpChn(int mod, int chn)                           { return 0; }

/* Video Decode */
int RK_MPI_VDEC_CreateChn(int chn, void *attr)                     { return 0; }
int RK_MPI_VDEC_DestroyChn(int chn)                                { return 0; }

/* Video Encode (extended) */
int RK_MPI_VENC_CreateChn(int chn, void *attr)                     { return 0; }
int RK_MPI_VENC_CreateJpegLightChn(int chn, void *attr)            { return 0; }
int RK_MPI_VENC_DestroyChn(int chn)                                { return 0; }
int RK_MPI_VENC_GetRcParam(int chn, void *p)                       { return 0; }
int RK_MPI_VENC_SetRcParam(int chn, void *p)                       { return 0; }
int RK_MPI_VENC_SetGop(int chn, int gop)                           { return 0; }
int RK_MPI_VENC_SetGopMode(int chn, void *attr)                    { return 0; }
int RK_MPI_VENC_SetRotation(int chn, int rot)                      { return 0; }
int RK_MPI_VENC_SetFps(int chn, void *fps)                         { return 0; }
int RK_MPI_VENC_SetBitrate(int chn, int bps, int mn, int mx)       { return 0; }
int RK_MPI_VENC_SetRcMode(int chn, int mode)                       { return 0; }
int RK_MPI_VENC_SetRcQuality(int chn, int q)                       { return 0; }
int RK_MPI_VENC_SetJpegParam(int chn, void *p)                     { return 0; }
int RK_MPI_VENC_SetAvcProfile(int chn, int profile, int level)     { return 0; }
int RK_MPI_VENC_SetResolution(int chn, void *attr)                 { return 0; }
int RK_MPI_VENC_SetVencChnAttr(int chn, void *attr)                { return 0; }
int RK_MPI_VENC_GetVencChnAttr(int chn, void *attr)                { return 0; }
int RK_MPI_VENC_SetChnParam(int chn, void *p)                      { return 0; }
int RK_MPI_VENC_GetChnParam(int chn, void *p)                      { return 0; }
int RK_MPI_VENC_SetRoiAttr(int chn, void *attr, int n)             { return 0; }
int RK_MPI_VENC_GetRoiAttr(int chn, void *attr, int n)             { return 0; }
int RK_MPI_VENC_SetSuperFrameStrategy(int chn, void *p)            { return 0; }
int RK_MPI_VENC_GetSuperFrameStrategy(int chn, void *p)            { return 0; }
int RK_MPI_VENC_RequestIDR(int chn, int instant)                   { return 0; }
int RK_MPI_VENC_StartRecvFrame(int chn, void *attr)                { return 0; }
int RK_MPI_VENC_QueryStatus(int chn, void *stat)                   { return 0; }
int RK_MPI_VENC_InsertUserData(int chn, void *data, int len)       { return 0; }
int RK_MPI_VENC_GetFd(int chn)                                     { return -1; }
int RK_MPI_VENC_RGN_Init(int chn, void *attr)                      { return 0; }
int RK_MPI_VENC_RGN_SetBitMap(int chn, void *r, void *bm)          { return 0; }
int RK_MPI_VENC_RGN_SetCover(int chn, void *r, void *c)            { return 0; }
int RK_MPI_VENC_RGN_SetCoverEx(int chn, void *r, void *c)          { return 0; }
int RK_MPI_VENC_RGN_SetPaletteId(int chn, void *r, void *p)        { return 0; }

/* Video Input (extended) */
int RK_MPI_VI_SetChnAttr(int pipe, int chn, void *attr)            { LOG("VI_SetChnAttr pipe=%d chn=%d attr=%p\n", pipe, chn, attr); return 0; }
int RK_MPI_VI_GetChnAttr(int pipe, int chn, void *attr)            { return 0; }
int RK_MPI_VI_EnableChn(int pipe, int chn)                         { LOG("VI_EnableChn pipe=%d chn=%d\n", pipe, chn); return 0; }
int RK_MPI_VI_DisableChn(int pipe, int chn)                        { LOG("VI_DisableChn pipe=%d chn=%d\n", pipe, chn); return 0; }
int RK_MPI_VI_StartChn(int pipe, int chn)                          { LOG("VI_StartChn pipe=%d chn=%d\n", pipe, chn); return 0; }
int RK_MPI_VI_StopChn(int pipe, int chn)                           { LOG("VI_StopChn pipe=%d chn=%d\n", pipe, chn); return 0; }
int RK_MPI_VI_StartStream(int pipe, int chn)                       { LOG("VI_StartStream pipe=%d chn=%d\n", pipe, chn); return 0; }
int RK_MPI_VI_GetStatus(int pipe, int chn, void *stat)             { return 0; }
int RK_MPI_VI_EnableUserPic(int pipe, int chn)                     { return 0; }
int RK_MPI_VI_DisableUserPic(int pipe, int chn)                    { return 0; }
int RK_MPI_VI_SetUserPic(int pipe, int chn, void *attr)            { return 0; }
int RK_MPI_VI_GetChnRegionLuma(int p, int c, void *r, void *l, int t) { return 0; }
int RK_MPI_VI_StartRegionLuma(int pipe, int chn)                   { return 0; }
int RK_MPI_VI_StopRegionLuma(int pipe, int chn)                    { return 0; }
int RK_MPI_VI_RGN_SetBitMap(int p, int c, void *r, void *bm)       { return 0; }
int RK_MPI_VI_RGN_SetCover(int p, int c, void *r, void *cv)        { return 0; }

/* Video Mix */
int RK_MPI_VMIX_CreateDev(int dev, void *attr)                     { return 0; }
int RK_MPI_VMIX_DestroyDev(int dev)                                { return 0; }
int RK_MPI_VMIX_EnableChn(int dev, int chn)                        { return 0; }
int RK_MPI_VMIX_DisableChn(int dev, int chn)                       { return 0; }
int RK_MPI_VMIX_ShowChn(int dev, int chn)                          { return 0; }
int RK_MPI_VMIX_HideChn(int dev, int chn)                          { return 0; }
int RK_MPI_VMIX_SetLineInfo(int dev, int chn, void *li)            { return 0; }
int RK_MPI_VMIX_GetChnRegionLuma(int d, int c, void *r, void *l, int t) { return 0; }
int RK_MPI_VMIX_GetRegionLuma(int dev, void *r, void *l, int t)    { return 0; }
int RK_MPI_VMIX_RGN_SetBitMap(int d, int c, void *r, void *bm)     { return 0; }
int RK_MPI_VMIX_RGN_SetCover(int d, int c, void *r, void *cv)      { return 0; }

/* Video Output */
int RK_MPI_VO_CreateChn(int layer, int chn, void *attr)            { return 0; }
int RK_MPI_VO_DestroyChn(int layer, int chn)                       { return 0; }
int RK_MPI_VO_SetChnAttr(int layer, int chn, void *attr)           { return 0; }
int RK_MPI_VO_GetChnAttr(int layer, int chn, void *attr)           { return 0; }

/* Video Process */
int RK_MPI_VP_EnableChn(int chn, void *attr)                       { return 0; }
int RK_MPI_VP_DisableChn(int chn)                                  { return 0; }
int RK_MPI_VP_SetChnAttr(int chn, void *attr)                      { return 0; }
