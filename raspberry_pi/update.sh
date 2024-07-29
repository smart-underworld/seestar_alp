#!/bin/bash -ex

src_home=$(cd $(dirname $0)/.. && pwd)


sudo systemctl stop seestar_device
sudo systemctl stop seestar_front

cd ${src_home}

if [ ! -e device/config.toml ]; then
  cp device/config.toml.example device/config.toml
  sed -i -e 's/127.0.0.1/0.0.0.0/g' device/config.toml
else
  cp device/config.toml device/config.toml.bak
fi

sudo  pip install -r requirements.txt --break-system-packages

cd raspberry_pi

cat systemd/seestar_device.service | sed -e "s|/home/.*/seestar_alp|$src_home|g" > /tmp/seestar_device.service
cat systemd/seestar_front.service | sed -e "s|/home/.*/seestar_alp|$src_home|g" > /tmp/seestar_front.service
sudo chown root:root /tmp/seestar*.service
sudo mv /tmp/seestar*.service /etc/systemd/system

sudo systemctl daemon-reload

sudo systemctl start seestar_device
sudo systemctl start seestar_front

if ! $(systemctl is-active --quiet seestar_device); then
  echo "ERROR: seestar_device is not running"
  systemctl status seestar_device
fi

if ! $(systemctl is-active --quiet seestar_front); then
  echo "ERROR: seestar_front is not running"
  systemctl status seestar_front
fi

cat <<_EOF
|-------------------------------------|
| Seestar_alp update complete         |
|                                     |
| You can access SSC via:             |
| http://$(hostname).local:5432       |
|                                     |
| Device logs can be found in         |
|  ./seestar_alp/logs                 |
|                                     |
| Systemd logs can be viewed via      |
| journalctl -u seestar_device        |
| journalctl -u seestar_front         |
|-------------------------------------|
_EOF
