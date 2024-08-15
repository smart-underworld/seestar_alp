#!/bin/bash -ex
#
# A script to capture a tcpdump from an iOS device, talking to a SeeStar
# This assumes the iOS device is attached to a mac, where this is running
#

UDID=$(system_profiler SPUSBDataType | sed -n -E -e '/(iPhone|iPad)/,/Serial/s/ *Serial Number: *(........)(.*)/\1-\2/p')
seestar_ip=$(ping -Q -c 1 seestar.local | grep PING | sed -e 's/.*(\(.*\)).*/\1/')

if [ -z "$UDID" ]; then
  echo "ERROR: UDID cannot be empty"
  exit 1
fi

if [ -z "$seestar_ip" ]; then
  echo "ERROR: seestar_ip cannot be empty"
  exit 1
fi

trap ctrl_c INT TERM
ctrl_c () {
    echo "Cleaning up"
    rvictl -x $UDID

    echo "Your capture can be found in ./tcpdump.pcap"
}

RVI=$(rvictl -s $UDID|grep SUCCEEDED|sed -e 's/.*interface \(.*\)$/\1/')
if [ -z "$RVI" ]; then
  echo "ERROR: RVI cannot be empty"
  exit 1
fi

echo "Starting tcpdump. Interact with app, and press control+c to finish"
sudo tcpdump -i rvi0 dst $seestar_ip or src $seestar_ip -w ./tcpdump.pcap

ctrl_c