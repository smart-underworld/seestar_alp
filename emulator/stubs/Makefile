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

clean:
	rm -f *.so *.so.1 mount_stub
