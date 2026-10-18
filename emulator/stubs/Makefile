CC     = gcc
CFLAGS = -shared -fPIC -O0 -Wall

all: librockchip_mpp.so.1 libeasymedia.so.1 librkaiq.so librknn_api.so libmedia-ctl.so libhwid.so mount_stub

librockchip_mpp.so.1: stub_mpp.c
	$(CC) $(CFLAGS) -Wl,-soname,$@ -o $@ $<

libeasymedia.so.1: stub_easymedia.c
	$(CC) $(CFLAGS) -Wl,-soname,$@ -o $@ $<

librkaiq.so: stub_rkaiq.c
	$(CC) $(CFLAGS) -Wl,-soname,$@ -o $@ $<

librknn_api.so: stub_rknn.c
	$(CC) $(CFLAGS) -Wl,-soname,$@ -o $@ $<

libmedia-ctl.so: stub_media_ctl.c
	$(CC) $(CFLAGS) -Wl,-soname,$@ -o $@ $<

libhwid.so: stub_hwid.c
	$(CC) $(CFLAGS) -g -funwind-tables -rdynamic -Wl,-soname,$@ -ldl -o $@ $<

mount_stub: stub_mount.c
	$(CC) -O0 -Wall -o $@ $<

# aarch64 (RV1126B Pro models) only: the 64-bit imager links Rockchip libraries
# the 32-bit one does not.  stub_rk64_generic.c is built once per soname;
# librknnrt.so is the same RKNN stub the 32-bit image ships as librknn_api.so.
ifneq (,$(findstring aarch64,$(shell $(CC) -dumpmachine)))
ARM64_LIBS = librockit.so librkrawstream.so librga.so.2 librtsp.so libtlog.so librknnrt.so
all: $(ARM64_LIBS)

librockit.so librkrawstream.so librga.so.2 librtsp.so libtlog.so: stub_rk64_generic.c
	$(CC) $(CFLAGS) -Wl,-soname,$@ -o $@ $<

librknnrt.so: stub_rknn.c
	$(CC) $(CFLAGS) -Wl,-soname,$@ -o $@ $<
endif

clean:
	rm -f *.so *.so.1 *.so.2 mount_stub
