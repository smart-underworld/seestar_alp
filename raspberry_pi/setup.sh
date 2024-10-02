#!/bin/bash -e

src_home=$(cd $(dirname $0)/.. && pwd)
source ${src_home}/raspberry_pi/common_functions.sh

validate_access

if [ -e seestar_alp ] || [ -e ~/seestar_alp ]; then
    echo "ERROR: Existing seestar_alp directory detected."
    echo "       You should run the raspberry_pi/update.sh script instead."
    exit 255
fi

git clone https://github.com/smart-underworld/seestar_alp.git
cd  seestar_alp

src_home=$(pwd)
mkdir -p logs

config_toml_setup
install_apt_packages
python_virtualenv_setup
systemd_service_setup
print_banner "setup"

