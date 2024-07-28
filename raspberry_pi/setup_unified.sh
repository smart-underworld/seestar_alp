#!/bin/bash -e

sudo apt-get update
sudo apt-get install -y git python3-pip

# git clone https://github.com/astrophotograph/seestar_alp.git
# cd  seestar_alp

src_home=$(pwd)
mkdir logs

sed -i -e 's/127.0.0.1/0.0.0.0/g' device/config.toml

sudo  pip install -r requirements.txt --break-system-packages

cd raspberry_pi
cat systemd/seestar_unified.service | sed -e "s|/home/.*/seestar_alp|$src_home|g" > /tmp/seestar_unified.service
sudo mv /tmp/seestar*.service /etc/systemd/system

sudo systemctl daemon-reload

sudo systemctl enable seestar_unified

sudo systemctl start seestar_unified

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
| journalctl -u seestar_device        |
| journalctl -u seestar_front         |
|-------------------------------------|
_EOF
