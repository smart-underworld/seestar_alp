#!/bin/bash -e
#
# This bootstraps the unified application on a Raspberry Pi.
# Note: it intentionally does _not_ start the services for...
#       reasons.
#

sudo apt-get update
sudo apt-get install -y git python3-pip
sudo rm -rf seestar_alp
sudo chown -R pi:pi .

git clone https://github.com/smart-underworld/seestar_alp.git
cd  seestar_alp

src_home=$(pwd)
mkdir logs

if [ ! -e device/config.toml ]; then
  cp device/config.toml.example device/config.toml
  sed -i -e 's/127.0.0.1/0.0.0.0/g' device/config.toml
fi

sudo  pip install -r requirements.txt --break-system-packages

cd raspberry_pi
cat systemd/seestar_unified.service | sed -e "s|/home/.*/seestar_alp|$src_home|g" > /tmp/seestar_unified.service
sudo mv /tmp/seestar*.service /etc/systemd/system

sudo systemctl enable seestar_unified

cat <<_EOF
|-------------------------------------|
| Seestar_alp Setup Complete          |
|                                     |
| You can access SSC via:             |
| http://$(hostname).local:5432       |
|                                     |
| Device logs can be found in         |
|  ./seestar_alp/logs                 |
|                                     |
| Systemd logs can be viewed via      |
| journalctl -u seestar_unified       |
|-------------------------------------|
_EOF
