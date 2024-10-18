#!/usr/bin/env bash

mkfifo /tmp/seestar

indiserver -f /tmp/seestar &

cd /home/seestar/seestar_alp/indi
python3 start_indi_devices.py

cd /home/seestar/seestar_alp
python3 ./root_app.py
