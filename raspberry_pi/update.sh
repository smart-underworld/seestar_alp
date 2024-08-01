#!/bin/bash -e

src_home=$(cd $(dirname $0)/.. && pwd)


if $(systemctl is-active --quiet seestar_device); then
  sudo systemctl stop seestar_device
fi

if $(systemctl is-active --quiet seestar_front); then
  sudo systemctl stop seestar_front
fi

if $(systemctl is-active --quiet seestar); then
  sudo systemctl stop seestar
fi

cd ${src_home}

if [ ! -e device/config.toml ]; then
  cp device/config.toml.example device/config.toml
  sed -i -e 's/127.0.0.1/0.0.0.0/g' device/config.toml
else
  cp device/config.toml device/config.toml.bak
fi

sudo  pip install -r requirements.txt --break-system-packages

cd raspberry_pi

cat systemd/seestar.service | sed -e "s|/home/.*/seestar_alp|$src_home|g" > /tmp/seestar.service
sudo chown root:root /tmp/seestar*.service

sudo rm -f /etc/systemd/system/seestar*
sudo mv /tmp/seestar*.service /etc/systemd/system

sudo systemctl daemon-reload

sudo systemctl enable seestar
sudo systemctl start seestar

if ! $(systemctl is-active --quiet seestar); then
  echo "ERROR: seestar service is not running"
  systemctl status seestar
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
| journalctl -u seestar               |
|                                     |
| Current status can be viewed via    |
| systemctl status seestar            |
|-------------------------------------|
_EOF
