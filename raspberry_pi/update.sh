#!/bin/bash -e

if [ "$(whoami)" = "root" ]; then
    echo "ERROR: You should not run this script as root"
    exit 255
fi

timeout 2 sudo id 2>&1 > /dev/null && sudo="true" || sudo="false"
if [ "$sudo" = "false" ]; then
    echo "ERROR: User does not have sudo access required for setup"
    exit 255
fi

src_home=$(cd $(dirname $0)/.. && pwd)

# check if update is required
cd "${src_home}"
git fetch origin
if [ $(git rev-parse HEAD) = $(git rev-parse @{u}) ]; then
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

if [ ! -e device/config.toml ]; then
  cp device/config.toml.example device/config.toml
  sed -i -e 's/127.0.0.1/0.0.0.0/g' device/config.toml
  sed -i -e 's|log_prefix =.*|log_prefix = "logs/"|g' device/config.toml
else
  cp device/config.toml device/config.toml.bak
fi

sudo apt-get update --yes
sudo apt-get install --yes libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev libgdbm-dev lzma lzma-dev tcl-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev wget curl make build-essential openssl libgl1

# pyenv
if [ ! -e ~/.pyenv ]; then
  curl https://pyenv.run | bash
  cat <<_EOF >> ~/.bashrc
# start seestar_alp
export PYENV_ROOT="\$HOME/.pyenv"
[[ -d \$PYENV_ROOT/bin ]] && export PATH="\$PYENV_ROOT/bin:\$PATH"
eval "\$(pyenv init -)"
eval "\$(pyenv virtualenv-init -)"
# end seestar_alp
_EOF

  export PYENV_ROOT="$HOME/.pyenv"
  [[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
  eval "$(pyenv init -)"
  eval "$(pyenv virtualenv-init -)"

  pyenv install 3.12.5
  pyenv virtualenv 3.12.5 ssc-3.12.5

  pyenv global ssc-3.12.5

else
  export PYENV_ROOT="$HOME/.pyenv"
  [[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
  eval "$(pyenv init -)"
  eval "$(pyenv virtualenv-init -)"
fi

git pull
pip install -r requirements.txt

cd raspberry_pi

cat systemd/seestar.service | sed \
  -e "s|/home/.*/seestar_alp|$src_home|g" \
  -e "s|^ExecStart=.*|ExecStart=$HOME/.pyenv/versions/ssc-3.12.5/bin/python3 $src_home/root_app.py|" > /tmp/seestar.service
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
