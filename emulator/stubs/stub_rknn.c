/*
 * Stub for librknn_api.so (Rockchip NPU inference)
 *
 * 7 symbols. Only called when an AI inference command is issued (start_ai_process),
 * not during startup — so these stubs just need to not crash. rknn_init fills
 * in the context handle; we set it to a non-zero sentinel so NULL checks pass.
 */
#include <stdint.h>

typedef uint64_t rknn_context;

int rknn_init(rknn_context *ctx, const void *model, uint32_t size, uint32_t flag) {
    if (ctx) *ctx = (rknn_context)0xdeadbeef;
    return 0;
}
int rknn_destroy(rknn_context ctx)                                              { return 0; }
int rknn_query(rknn_context ctx, int cmd, void *info, uint32_t size)            { return 0; }
int rknn_inputs_set(rknn_context ctx, uint32_t n, void *inputs)                 { return 0; }
int rknn_run(rknn_context ctx, void *extend)                                    { return 0; }
int rknn_outputs_get(rknn_context ctx, uint32_t n, void *outputs, void *extend) { return 0; }
int rknn_outputs_release(rknn_context ctx, uint32_t n, void *outputs)           { return 0; }
