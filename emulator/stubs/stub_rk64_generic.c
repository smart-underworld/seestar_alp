/*
 * Generic no-op stubs for the Rockchip userland libraries the aarch64
 * (RV1126B: S30 Pro / S50 Pro / S30 Plus / S80) zwoair_imager and libasisdk
 * link against: librockit, librkrawstream, librga, librtsp, libtlog.
 *
 * The same object is built under each of those sonames (see the Makefile);
 * every function simply returns 0, which the imager treats as success.  This is
 * enough for the emulator because camera frames do NOT come through these
 * libraries here: stub_hwid.c fakes the V4L2 capture path (/dev/video0) that
 * libasisdk's ASI_CAM_GetFrame actually reads.  These only have to exist so the
 * dynamic loader can resolve libasisdk's imports.
 *
 * Regenerate the list after a firmware bump with:
 *   ldd -r <iscope_64>/bin/zwoair_imager <iscope_64>/lib/libasisdk.so
 * inside the arm64 image and add any new "undefined symbol" lines whose names start with RK_, rk, tlog_ or rtsp.
 * Symbols librkaiq (stub_rkaiq.c) and librknnrt (stub_rknn.c) already define are
 * intentionally absent.
 */

/* RK_MPI/RK_TDE (Rockit media pipeline: VI/VPSS/VENC/RGN/SYS/TDE) */
long RK_MPI_CAL_COMM_GetPicBufferSize(void) { return 0; }
long RK_MPI_CAL_TDE_GetPicBufferSize(void) { return 0; }
long RK_MPI_MB_GetLength(void) { return 0; }
long RK_MPI_MB_Handle2VirAddr(void) { return 0; }
long RK_MPI_RGN_AttachToChn(void) { return 0; }
long RK_MPI_RGN_Create(void) { return 0; }
long RK_MPI_RGN_Destroy(void) { return 0; }
long RK_MPI_RGN_DetachFromChn(void) { return 0; }
long RK_MPI_RGN_GetDisplayAttr(void) { return 0; }
long RK_MPI_RGN_SetBitMap(void) { return 0; }
long RK_MPI_RGN_SetDisplayAttr(void) { return 0; }
long RK_MPI_SYS_Free(void) { return 0; }
long RK_MPI_SYS_MmzAlloc(void) { return 0; }
long RK_MPI_VENC_GetChnAttr(void) { return 0; }
long RK_MPI_VENC_GetChnParam(void) { return 0; }
long RK_MPI_VENC_GetStream(void) { return 0; }
long RK_MPI_VENC_ReleaseStream(void) { return 0; }
long RK_MPI_VENC_SendFrame(void) { return 0; }
long RK_MPI_VENC_SetChnAttr(void) { return 0; }
long RK_MPI_VENC_SetChnParam(void) { return 0; }
long RK_MPI_VENC_SetChnRotation(void) { return 0; }
long RK_MPI_VENC_SetSliceSplit(void) { return 0; }
long RK_MPI_VENC_StartRecvFrame(void) { return 0; }
long RK_MPI_VENC_StopRecvFrame(void) { return 0; }
long RK_MPI_VI_DisableDev(void) { return 0; }
long RK_MPI_VI_EnableDev(void) { return 0; }
long RK_MPI_VI_GetChnAttr(void) { return 0; }
long RK_MPI_VI_GetChnFrame(void) { return 0; }
long RK_MPI_VI_GetDevAttr(void) { return 0; }
long RK_MPI_VI_GetDevIsEnable(void) { return 0; }
long RK_MPI_VI_PauseChn(void) { return 0; }
long RK_MPI_VI_QueryDevStatus(void) { return 0; }
long RK_MPI_VI_ReleaseChnFrame(void) { return 0; }
long RK_MPI_VI_ResumeChn(void) { return 0; }
long RK_MPI_VI_SetDevAttr(void) { return 0; }
long RK_MPI_VI_SetDevBindPipe(void) { return 0; }
long RK_MPI_VPSS_CreateGrp(void) { return 0; }
long RK_MPI_VPSS_DestroyGrp(void) { return 0; }
long RK_MPI_VPSS_DisableChn(void) { return 0; }
long RK_MPI_VPSS_EnableChn(void) { return 0; }
long RK_MPI_VPSS_GetChnAttr(void) { return 0; }
long RK_MPI_VPSS_GetChnCrop(void) { return 0; }
long RK_MPI_VPSS_GetChnFrame(void) { return 0; }
long RK_MPI_VPSS_GetGrpCrop(void) { return 0; }
long RK_MPI_VPSS_ReleaseChnFrame(void) { return 0; }
long RK_MPI_VPSS_SetChnAttr(void) { return 0; }
long RK_MPI_VPSS_SetChnCrop(void) { return 0; }
long RK_MPI_VPSS_SetGrpCrop(void) { return 0; }
long RK_MPI_VPSS_StartGrp(void) { return 0; }
long RK_MPI_VPSS_StopGrp(void) { return 0; }
long RK_TDE_BeginJob(void) { return 0; }
long RK_TDE_Close(void) { return 0; }
long RK_TDE_EndJob(void) { return 0; }
long RK_TDE_Open(void) { return 0; }
long RK_TDE_QuickCopy(void) { return 0; }
long RK_TDE_QuickResize(void) { return 0; }
long RK_TDE_Rotate(void) { return 0; }
long RK_TDE_WaitForDone(void) { return 0; }

/* rtsp (RTSP server) */
long create_rtsp_demo(void) { return 0; }
long rtsp_del_demo(void) { return 0; }
long rtsp_del_session(void) { return 0; }
long rtsp_do_event(void) { return 0; }
long rtsp_get_ntptime(void) { return 0; }
long rtsp_get_reltime(void) { return 0; }
long rtsp_new_session(void) { return 0; }
long rtsp_set_video(void) { return 0; }
long rtsp_sync_video_ts(void) { return 0; }
long rtsp_tx_audio(void) { return 0; }
long rtsp_tx_video(void) { return 0; }

/* rk_aiq (ISP/3A control not already covered by stub_rkaiq.c) */
long rk_aiq_uapi2_getFocusMode(void) { return 0; }
long rk_aiq_uapi2_getFocusRange(void) { return 0; }
long rk_aiq_uapi2_getFocusWin(void) { return 0; }
long rk_aiq_uapi2_getSaturation(void) { return 0; }
long rk_aiq_uapi2_getSearchResult(void) { return 0; }
long rk_aiq_uapi2_getWBGain(void) { return 0; }
long rk_aiq_uapi2_oneshotFocus(void) { return 0; }
long rk_aiq_uapi2_setExpMode(void) { return 0; }
long rk_aiq_uapi2_setFocusMode(void) { return 0; }
long rk_aiq_uapi2_setFocusPosition(void) { return 0; }
long rk_aiq_uapi2_setFocusWin(void) { return 0; }
long rk_aiq_uapi2_setMWBGain(void) { return 0; }
long rk_aiq_uapi2_setSaturation(void) { return 0; }
long rk_aiq_uapi2_setWBMode(void) { return 0; }
long rk_aiq_uapi2_sysctl_deinit(void) { return 0; }
long rk_aiq_uapi2_sysctl_enumStaticMetas(void) { return 0; }
long rk_aiq_uapi2_sysctl_init(void) { return 0; }
long rk_aiq_uapi2_sysctl_prepare(void) { return 0; }
long rk_aiq_uapi2_sysctl_rawReproc_preInit(void) { return 0; }
long rk_aiq_uapi2_sysctl_setMulCamConc(void) { return 0; }
long rk_aiq_uapi2_sysctl_start(void) { return 0; }
long rk_aiq_uapi2_sysctl_stop(void) { return 0; }
long rk_aiq_uapi2_sysctl_switch_scene(void) { return 0; }
long rk_aiq_user_api2_ae_getExpSwAttr(void) { return 0; }
long rk_aiq_user_api2_ae_getHdrExpAttr(void) { return 0; }
long rk_aiq_user_api2_ae_getLinExpAttr(void) { return 0; }
long rk_aiq_user_api2_ae_queryExpResInfo(void) { return 0; }
long rk_aiq_user_api2_ae_setExpSwAttr(void) { return 0; }
long rk_aiq_user_api2_ae_setHdrExpAttr(void) { return 0; }
long rk_aiq_user_api2_ae_setLinExpAttr(void) { return 0; }
long rk_aiq_user_api2_af_GetAttrib(void) { return 0; }
long rk_aiq_user_api2_sharp_GetStrength(void) { return 0; }
long rk_aiq_user_api2_sharp_SetStrength(void) { return 0; }

/* rkrawstream (raw sensor capture / ISP readback) */
long rkrawstream_readback_init(void) { return 0; }
long rkrawstream_readback_prepare(void) { return 0; }
long rkrawstream_readback_set_rkraw2(void) { return 0; }
long rkrawstream_readback_start(void) { return 0; }
long rkrawstream_readback_stop(void) { return 0; }
long rkrawstream_setup_pipline_fmt(void) { return 0; }
long rkrawstream_uapi_deinit(void) { return 0; }
long rkrawstream_uapi_init(void) { return 0; }
long rkrawstream_vicap_buf_return(void) { return 0; }
long rkrawstream_vicap_buf_take(void) { return 0; }
long rkrawstream_vicap_init(void) { return 0; }
long rkrawstream_vicap_prepare(void) { return 0; }
long rkrawstream_vicap_start(void) { return 0; }
long rkrawstream_vicap_stop(void) { return 0; }

/* tlog (Rockchip logging) */
long tlog_getlevel(void) { return 0; }
long tlog_init(void) { return 0; }
long tlog_setlevel(void) { return 0; }
long tlog_vext(void) { return 0; }
