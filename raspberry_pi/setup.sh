#!/bin/bash -e
#
# This bootstraps the unified application on a Raspberry Pi.
#
if [ -e seestar_alp ] || [ -e ~/seestar_alp ]; then
    echo "ERROR: Existing seestar_alp directory detected."
    echo "       You should run the raspberry_pi/update.sh script instead."
    exit 255
fi

sudo apt-get update
sudo apt-get install -y git python3-pip

git clone https://github.com/smart-underworld/seestar_alp.git
cd  seestar_alp

src_home=$(pwd)
mkdir -p logs

if [ ! -e device/config.toml ]; then
    sed -e 's/127.0.0.1/0.0.0.0/g' device/config.toml.example > device/config.toml
    sed -i -e 's|log_prefix =.*|log_prefix = "logs/"|g' device/config.toml
fi

sudo  pip install -r requirements.txt --break-system-packages

cd raspberry_pi
cat systemd/seestar.service | sed -e "s|/home/.*/seestar_alp|$src_home|g" > /tmp/seestar.service
sudo mv /tmp/seestar.service /etc/systemd/system

sudo systemctl daemon-reload

sudo systemctl enable seestar
sudo systemctl start seestar

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
| journalctl -u seestar               |
|                                     |
| Current status can be viewed via    |
| systemctl status seestar            |
|-------------------------------------|
_EOF
