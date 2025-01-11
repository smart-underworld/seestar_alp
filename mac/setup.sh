#!/bin/bash
src_home=$(cd $(dirname $0)/.. && pwd)

#
# common functions
#
function validate_access {
  if [ "$(whoami)" = "root" ]; then
    echo "ERROR: You should not run this script as root"
    exit 255
  fi

  if [ "$(uname)" != "Darwin" ]; then
    echo "ERROR: You should only run this script on a Mac"
  fi
}

function config_toml_setup {
  if [ ! -e device/config.toml ]; then
    cp device/config.toml.example device/config.toml
  else
    cp device/config.toml device/config.toml.bak
  fi
}

function python_virtualenv_setup {
  if [ ! -e ~/.pyenv ]; then
    curl https://pyenv.run | bash

    if [ "$SHELL" = "/bin/bash" ]; then
      shellfile=~/.bashrc
    else
      shellfile=~/.zshrc
    fi

    cat <<_EOF >> ${shellfile}
# start seestar_alp
export PYENV_ROOT="\$HOME/.pyenv"
[[ -d \$PYENV_ROOT/bin ]] && export PATH="\$PYENV_ROOT/bin:\$PATH"
eval "\$(pyenv init -)"
eval "\$(pyenv virtualenv-init -)"
# end seestar_alp
_EOF
  else
    echo "Pyenv already configured, skipping install"
  fi

  export PYENV_ROOT="$HOME/.pyenv"
  [[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
  eval "$(pyenv init -)"
  eval "$(pyenv virtualenv-init -)"

  if [ ! -e ~/.pyenv/versions/3.12.5 ]; then
    pyenv install 3.12.5
  else
    echo "python 3.12.5 exists, skipping install"
  fi

  if [ ! -e ~/.pyenv/versions/ssc-3.12.5 ]; then
    pyenv virtualenv 3.12.5 ssc-3.12.5
  else
    echo "Python virtual environment for SSC exists - skipping install"
  fi
  if  [ ! -e ./.python-version ]; then
    pyenv local ssc-3.12.5
  else
    echo "Python local virtual environment already configured"
  fi

  pip install -r requirements.txt
}

function print_banner {
  local operation="$1"
  local host=$(hostname)
  cat <<_EOF
|-------------------------------------|
$(printf "| %-36s|" "Seestar_alp ${operation} complete")
|                                     |
| To run SSC, run:                    |
|  cd seestar_alp                     |
|  python3 ./root_app.py              |
|                                     |
| logs can be found in                |
|  ./seestar_alp/alpyca.log*          |
|                                     |
|-------------------------------------|
_EOF
}

#
# main setup script
#
function setup() {
  validate_access

  if [ ! -e ${src_home}/../seestar_alp ]; then
    git clone https://github.com/smart-underworld/seestar_alp.git
    cd seestar_alp
    action="setup"
  else
    action="update"
    cd ${src_home}
    git pull
  fi

  config_toml_setup
  python_virtualenv_setup
  print_banner "${action}"
}

#
# run setup if not sourced from another file
#
(return 0 2>/dev/null) && sourced=1 || sourced=0
if [ ${sourced} = 0 ]; then
  setup
fi
