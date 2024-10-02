#!/bin/bash -e
src_home=$(cd $(dirname $0)/.. && pwd)
source ${src_home}/raspberry_pi/common_functions.sh

validate_access

if [ "$1" = "--force" ]; then
    FORCE=true
fi


# check if update is required
cd "${src_home}"
git fetch origin
if [ $(git rev-parse HEAD) = $(git rev-parse @{u}) ] && [ "${FORCE}" != "true" ]; then
    echo "Nothing to do, you're already up-to-date!"
    exit 0
fi

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

# Perform any update operations here, that need to change
# prior behavior on the system
user=$(whoami)
group=$(id -gn)
if [ -d ./logs ]; then
    sudo chown ${user}:${group} ./logs/* || true
else
    mkdir logs
fi

config_toml_setup
install_apt_packages
python_virtualenv_setup
systemd_service_setup
print_banner "update"
