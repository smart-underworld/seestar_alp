#!/bin/bash

# Check we are running as root
if ! [ $(id -u) = 0 ]; then
    echo "You must run this script as sudo, or root"
	exit 1
fi

apt-get update
apt-get install -y git python3-pip

git clone https://github.com/smart-underworld/seestar_alp.git
cd  seestar_alp

pip install -r requirements.txt --break-system-packages

username=$(logname)
cd raspberry_pi
cat systemd/seestar_device.service | sed -e "s/<username>/$username/g" > /etc/systemd/system/seestar_device.service
cat systemd/seestar_front.service | sed -e "s/<username>/$username/g" > /etc/systemd/system/seestar_front.service

systemctl daemon-reload

systemctl enable seestar_device
systemctl enable seestar_front

systemctl start seestar_device
systemctl start seestar_front