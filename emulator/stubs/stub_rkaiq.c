/*
 * Stub for librkaiq.so (Rockchip ISP/AiQ pipeline)
 *
 * 62 symbols. The four sysctl_* functions are the critical startup path:
 *   init → prepare → start
 * rk_aiq_uapi_sysctl_init MUST return non-NULL (it's a context pointer used
 * by every subsequent call). All other functions just need to return 0.
 *
 * Logging on frame-delivery API so we can trace which mechanism the binary
 * uses to receive raw capture callbacks from the ISP pipeline.
 */
#include <stddef.h>
#include <stdio.h>

#define LOG(...) do { fprintf(stderr, "[rkaiq] " __VA_ARGS__); fflush(stderr); } while(0)

static int _aiq_ctx;

/* Lifecycle — critical startup path */
void *rk_aiq_uapi_sysctl_init(const char *sns_ent_name, const char *iq_file_dir,
                               void *err_cb, void *metas_cb) {
    LOG("sysctl_init sns=%s iq_dir=%s err_cb=%p metas_cb=%p\n",
        sns_ent_name ? sns_ent_name : "(null)",
        iq_file_dir  ? iq_file_dir  : "(null)",
        err_cb, metas_cb);
    return &_aiq_ctx;
}
int rk_aiq_uapi_sysctl_prepare(void *ctx, unsigned int w, unsigned int h, int mode) {
    LOG("sysctl_prepare w=%u h=%u mode=%d\n", w, h, mode);
    return 0;
}
int rk_aiq_uapi_sysctl_start(void *ctx)  { LOG("sysctl_start\n"); return 0; }
int rk_aiq_uapi_sysctl_stop(void *ctx, int t)   { LOG("sysctl_stop t=%d\n", t); return 0; }
int rk_aiq_uapi_sysctl_deinit(void *ctx)        { LOG("sysctl_deinit\n"); return 0; }
int rk_aiq_uapi_sysctl_enumStaticMetas(void *metas)                                 { return 0; }
int rk_aiq_uapi_sysctl_regRawCapCb(void *ctx, void *cb) {
    LOG("regRawCapCb ctx=%p cb=%p\n", ctx, cb);
    return 0;
}
int rk_aiq_uapi_sysctl_releaseRawCapBuf(void *ctx, void *buf) {
    LOG("releaseRawCapBuf ctx=%p buf=%p\n", ctx, buf);
    return 0;
}
int rk_aiq_uapi_sysctl_setCpsLtCfg(void *ctx, void *cfg)                            { return 0; }
int rk_aiq_uapi_sysctl_setCrop(void *ctx, void *crop)                               { return 0; }
int rk_aiq_uapi_sysctl_setModuleCtl(void *ctx, unsigned long mod, int en)           { return 0; }
int rk_aiq_uapi_sysctl_setMulCamConc(void *ctx, int en)                             { return 0; }
int rk_aiq_uapi_sysctl_setSharpFbcRotation(void *ctx, int rot)                      { return 0; }
int rk_aiq_uapi_sysctl_swWorkingModeDyn(void *ctx, int mode)                        { return 0; }
int rk_aiq_uapi_sysctl_updateIq(void *ctx, char *iq_file)                           { return 0; }

/* Dehazing */
int rk_aiq_uapi_disableDhz(void *ctx)                                               { return 0; }
int rk_aiq_uapi_enableDhz(void *ctx)                                                { return 0; }
int rk_aiq_uapi_setDhzMode(void *ctx, unsigned int mode)                            { return 0; }
int rk_aiq_uapi_setMDhzStrth(void *ctx, int en, unsigned int s)                     { return 0; }

/* Brightness / Contrast / Saturation / Sharpness */
int rk_aiq_uapi_setBrightness(void *ctx, unsigned int val)                          { return 0; }
int rk_aiq_uapi_setContrast(void *ctx, unsigned int val)                            { return 0; }
int rk_aiq_uapi_setSaturation(void *ctx, unsigned int val)                          { return 0; }
int rk_aiq_uapi_setSharpness(void *ctx, unsigned int val)                           { return 0; }
int rk_aiq_uapi_setDarkAreaBoostStrth(void *ctx, unsigned int val)                  { return 0; }
int rk_aiq_uapi_getBrightness(void *ctx, unsigned int *val)    { if (val) *val = 50; return 0; }
int rk_aiq_uapi_getSharpness(void *ctx, unsigned int *val)     { if (val) *val = 50; return 0; }

/* BLC / HLC */
int rk_aiq_uapi_setBLCMode(void *ctx, int en, int strength)                         { return 0; }
int rk_aiq_uapi_setBLCStrength(void *ctx, int strength)                             { return 0; }
int rk_aiq_uapi_setHLCMode(void *ctx, int en)                                       { return 0; }
int rk_aiq_uapi_setHLCStrength(void *ctx, int strength)                             { return 0; }

/* Exposure */
int rk_aiq_uapi_setManualExp(void *ctx, float gain, float time)                     { return 0; }
int rk_aiq_uapi_setExpGainRange(void *ctx, void *r)                                 { return 0; }
int rk_aiq_uapi_setExpTimeRange(void *ctx, void *r)                                 { return 0; }
int rk_aiq_uapi_setExpPwrLineFreqMode(void *ctx, int mode)                          { return 0; }
int rk_aiq_uapi_setFrameRate(void *ctx, void *fps)                                  { return 0; }
int rk_aiq_uapi_getExpGainRange(void *ctx, void *r)                                 { return 0; }
int rk_aiq_uapi_getExpTimeRange(void *ctx, void *r)                                 { return 0; }

/* White Balance */
int rk_aiq_uapi_setWBMode(void *ctx, int mode)                                      { return 0; }
int rk_aiq_uapi_setMWBGain(void *ctx, void *gain)                                   { return 0; }
int rk_aiq_uapi_setMWBScene(void *ctx, void *scene)                                 { return 0; }
int rk_aiq_uapi_getMWBGain(void *ctx, void *gain)                                   { return 0; }
int rk_aiq_uapi_getMWBScene(void *ctx, void *scene)                                 { return 0; }

/* Noise Reduction */
int rk_aiq_uapi_setMSpaNRStrth(void *ctx, int en, unsigned int s)                   { return 0; }
int rk_aiq_uapi_setMTNRStrth(void *ctx, int en, unsigned int s)                     { return 0; }
int rk_aiq_uapi_getMSpaNRStrth(void *ctx, int *on, unsigned int *s)                 { return 0; }
int rk_aiq_uapi_getMTNRStrth(void *ctx, int *on, unsigned int *s)                   { return 0; }

/* Lens distortion / FEC / LDCH */
int rk_aiq_uapi_setFecEn(void *ctx, int en)                                         { return 0; }
int rk_aiq_uapi_setLdchEn(void *ctx, int en)                                        { return 0; }
int rk_aiq_uapi_setLdchCorrectLevel(void *ctx, int level)                           { return 0; }

/* Mirror / Flip */
int rk_aiq_uapi_setMirroFlip(void *ctx, int mirror, int flip)                       { return 0; }

/* Raw capture */
int rk_aiq_uapi_setRawStorageMemMode(void *ctx, int mode)                           { return 0; }
int rk_aiq_uapi_setWorkByUserTrig(void *ctx, int en)                                { return 0; }

/* AWB (Auto White Balance) */
int rk_aiq_user_api_awb_GetAttrib(void *ctx, void *attr)                            { return 0; }
int rk_aiq_user_api_awb_GetCCT(void *ctx, void *cct)                               { return 0; }
int rk_aiq_user_api_awb_SetAttrib(void *ctx, void *attr)                            { return 0; }

/* CCM (Color Correction Matrix) */
int rk_aiq_user_api_accm_GetAttrib(void *ctx, void *attr)                           { return 0; }
int rk_aiq_user_api_accm_SetAttrib(void *ctx, void *attr)                           { return 0; }

/* AE (Auto Exposure) */
int rk_aiq_user_api_ae_getExpSwAttr(void *ctx, void *attr)                          { return 0; }
int rk_aiq_user_api_ae_getLinExpAttr(void *ctx, void *attr)                         { return 0; }
int rk_aiq_user_api_ae_queryExpResInfo(void *ctx, void *info)                       { return 0; }
int rk_aiq_user_api_ae_setExpSwAttr(void *ctx, void *attr)                          { return 0; }
int rk_aiq_user_api_ae_setLinExpAttr(void *ctx, void *attr)                         { return 0; }
