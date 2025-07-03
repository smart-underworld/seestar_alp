#!/usr/bin/env bash

mkfifo /tmp/seestar

indiserver -f /tmp/seestar &

cd $SEESTAR_ALP_DIR/indi
python3 start_indi_devices.py

cd $SEESTAR_ALP_DIR
python3 ./root_app.py
