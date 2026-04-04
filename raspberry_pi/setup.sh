#!/bin/bash -e

# Optional proxy integration flags (may be set by caller or inherited via env)
WITH_PROXY="${WITH_PROXY:-false}"
SEESTAR_PROXY_UPSTREAM="${SEESTAR_PROXY_UPSTREAM:-seestar.local}"
SEESTAR_PROXY_HOOKS="${SEESTAR_PROXY_HOOKS:-}"        # colon-separated hook paths
SEESTAR_PROXY_CONFIG_DIRTY="${SEESTAR_PROXY_CONFIG_DIRTY:-false}"  # rewrite config only when explicitly changed

#
# common functions
#
function validate_access {
  if [ "$(whoami)" = "root" ]; then
    echo "ERROR: You should not run this script as root"
    exit 255
  fi

  sudo -n id 2>&1 > /dev/null && sudo="true" || sudo="false"
  if [ "$sudo" = "false" ]; then
    echo "ERROR: User does not have sudo access required for setup"
    exit 255
  fi

  if [ "$(arch)" != "aarch64" ]; then
    echo "ERROR: Unsupported architecture. Please ensure you are running the 64bit raspberry pi OS"
    exit 255
  fi

  if [ "$(uname)" != "Linux" ]; then
    echo "ERROR: You should only run this script on a Linux machine"
  fi
}

function install_apt_packages {
  sudo apt-get update --yes
  if grep -q trixie /etc/os-release; then
      # trixie
      sudo apt-get install --yes \
          git libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
          libsqlite3-dev llvm libncurses-dev \
          xz-utils tk-dev libgdbm-dev lzma tcl-dev \
          libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
          wget curl make build-essential openssl libgl1 indi-bin
  else
      # bookworm
      sudo apt-get install --yes software-properties-common \
          git libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
          libsqlite3-dev llvm libncurses5-dev libncursesw5-dev \
          xz-utils tk-dev libgdbm-dev lzma lzma-dev tcl-dev \
          libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
          wget curl make build-essential openssl libgl1 indi-bin
  fi
}

function config_toml_setup {
  if [ ! -e device/config.toml ]; then
    cp device/config.toml.example device/config.toml
    sed -i -e 's/127.0.0.1/0.0.0.0/g' device/config.toml
    sed -i -e 's|log_prefix =.*|log_prefix = "logs/"|g' device/config.toml
  else
    cp device/config.toml device/config.toml.bak
  fi
  if [ "${WITH_PROXY}" = "true" ]; then
    sed -i -e 's|ip_address = "seestar.local"|ip_address = "127.0.0.1"|g' device/config.toml
    echo "config.toml: seestars ip_address set to 127.0.0.1 (seestar-proxy)"
  fi
}

function install_seestar_proxy {
  local upstream_ip="${SEESTAR_PROXY_UPSTREAM:-seestar.local}"
  local api_url="https://api.github.com/repos/astrophotograph/seestar-proxy/releases/latest"

  echo "Fetching latest seestar-proxy release..."
  local version
  version=$(curl -fsSL "${api_url}" | grep '"tag_name"' | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
  if [ -z "${version}" ]; then
    echo "ERROR: Could not determine latest seestar-proxy version"
    exit 1
  fi

  # The deb ships the binary (/usr/bin/seestar-proxy) and systemd service
  local deb_name="seestar-proxy_${version#v}_arm64.deb"
  local download_url="https://github.com/astrophotograph/seestar-proxy/releases/download/${version}/${deb_name}"
  echo "Downloading ${deb_name}..."
  curl -fSL -o /tmp/seestar-proxy.deb "${download_url}"
  sudo dpkg -i /tmp/seestar-proxy.deb
  rm /tmp/seestar-proxy.deb

  # Write /etc/seestar-proxy/config.toml on first install or when explicitly changed.
  # Preserves manual edits on plain updates.
  sudo mkdir -p /etc/seestar-proxy
  if [ ! -e /etc/seestar-proxy/config.toml ] || [ "${SEESTAR_PROXY_CONFIG_DIRTY}" = "true" ]; then
    # Build optional hooks array
    local hooks_line=""
    if [ -n "${SEESTAR_PROXY_HOOKS}" ]; then
      hooks_line='hooks = ['
      local first=true
      local IFS_ORIG="${IFS}"
      IFS=':'
      for hook in ${SEESTAR_PROXY_HOOKS}; do
        [ "${first}" = "true" ] && hooks_line="${hooks_line}\"${hook}\"" || hooks_line="${hooks_line}, \"${hook}\""
        first=false
      done
      IFS="${IFS_ORIG}"
      hooks_line="${hooks_line}]"
    fi

    {
      echo "upstream = \"${upstream_ip}\""
      echo "discovery = true"
      [ -n "${hooks_line}" ] && echo "${hooks_line}"
    } | sudo tee /etc/seestar-proxy/config.toml > /dev/null
    echo "seestar-proxy: wrote /etc/seestar-proxy/config.toml"
  else
    echo "seestar-proxy: preserving existing /etc/seestar-proxy/config.toml"
  fi

  sudo systemctl daemon-reload
  sudo systemctl enable seestar-proxy

  if $(systemctl is-active --quiet seestar-proxy); then
    sudo systemctl restart seestar-proxy
  else
    sudo systemctl start seestar-proxy
  fi

  if ! $(systemctl is-active --quiet seestar-proxy); then
    echo "ERROR: seestar-proxy service is not running"
    systemctl status seestar-proxy
    exit 255
  fi

  echo "seestar-proxy ${version} installed (upstream: ${upstream_ip})"
}

function python_virtualenv_setup {
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

    pyenv install 3.13.5
    pyenv virtualenv 3.13.5 ssc-3.13.5

    pyenv global ssc-3.13.5

  else
    export PYENV_ROOT="$HOME/.pyenv"
    [[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"
    eval "$(pyenv virtualenv-init -)"

    pyenv update
    if [ ! -e ~/.pyenv/versions/3.13.5 ]; then
      pyenv install 3.13.5
    else
      echo "python 3.13.5 exists, skipping install"
    fi
    if [ ! -e ~/.pyenv/versions/ssc-3.13.5 ]; then
      pyenv virtualenv 3.13.5 ssc-3.13.5
    else
      echo "Python virtual environment for SSC exists - skipping install"
    fi
    if  [ "$(cat ~/.pyenv/version)" != "ssc-3.13.5" ]; then
      pyenv global ssc-3.13.5
    fi
  fi

  pip install -r requirements.txt
}

function systemd_service_setup {
  cd raspberry_pi

  cat systemd/seestar.env |sed -e "s/<username>/$USER/g" > /tmp/seestar.env

  cat systemd/seestar.service | sed \
  -e "s|/home/.*/seestar_alp|$src_home|g" \
  -e "s|^User=.*|User=${user}|g" \
  -e "s|^ExecStart=.*|ExecStart=$HOME/.pyenv/versions/ssc-3.13.5/bin/python3 $src_home/root_app.py|" > /tmp/seestar.service

  cat systemd/INDI.service | sed \
  -e "s|/home/.*/seestar_alp|$src_home|g" \
  -e "s|^ExecStartPost=python3|ExecStartPost=$HOME/.pyenv/versions/ssc-3.13.5/bin/python3|" \
  -e "s|^User=.*|User=${user}|g" > /tmp/INDI.service

  sudo chown root:root /tmp/seestar.service /tmp/INDI.service /tmp/seestar.env
  sudo mv /tmp/seestar.service /etc/systemd/system
  sudo mv /tmp/INDI.service /etc/systemd/system
  sudo mv /tmp/seestar.env /etc

  sudo systemctl daemon-reload

  sudo systemctl enable seestar
  sudo systemctl start seestar

  sudo systemctl enable INDI
  sudo systemctl start INDI

  # INDI service left disabled

  if ! $(systemctl is-active --quiet seestar); then
    echo "ERROR: seestar service is not running"
    systemctl status seestar
    exit 255
  fi
}

function network_config {
  sudo bash -c 'echo "net.ipv6.conf.all.disable_ipv6 = 1" > /etc/sysctl.d/98-ssc.conf'
  sudo touch /etc/sysctl.conf
  sudo sysctl -p
}

function print_banner {
  local operation="$1"
  local host=$(hostname)
  cat <<_EOF
|-------------------------------------|
$(printf "| %-36s|" "Seestar_alp ${operation} complete")
|                                     |
| You can access SSC via:             |
$(printf "| %-36s|" "http://${host}.local:5432")
|                                     |
| Device logs can be found in         |
|  ./seestar_alp/logs                 |
|                                     |
| Systemd logs can be viewed via      |
| journalctl -u seestar               |
| journalctl -u INDI                  |
|                                     |
| Current status can be viewed via    |
| systemctl status seestar            |
| systemctl status INDI               |
_EOF
  if [ "${WITH_PROXY}" = "true" ]; then
    cat <<_EOF
|                                     |
| seestar-proxy is enabled            |
$(printf "| %-36s|" "  upstream: ${SEESTAR_PROXY_UPSTREAM}")
| journalctl -u seestar-proxy         |
| systemctl status seestar-proxy      |
_EOF
  fi
  echo "|-------------------------------------|"
}

#
# main setup script
#
function setup() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --with-proxy)
        export WITH_PROXY=true
        shift
        ;;
      --seestar-ip)
        export SEESTAR_PROXY_UPSTREAM="$2"
        export SEESTAR_PROXY_CONFIG_DIRTY=true
        shift 2
        ;;
      --proxy-hook)
        export WITH_PROXY=true
        export SEESTAR_PROXY_HOOKS="${SEESTAR_PROXY_HOOKS:+${SEESTAR_PROXY_HOOKS}:}$2"
        export SEESTAR_PROXY_CONFIG_DIRTY=true
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done

  validate_access

  if [ -e seestar_alp ] || [ -e ~/seestar_alp ]; then
    echo "ERROR: Existing seestar_alp directory detected."
    echo "       You should run the raspberry_pi/update.sh script instead."
    exit 255
  fi

  install_apt_packages
  git clone https://github.com/smart-underworld/seestar_alp.git
  cd  seestar_alp

  user=$(whoami)
  group=$(id -gn)
  src_home=$(pwd)
  mkdir -p logs

  config_toml_setup
  python_virtualenv_setup
  network_config
  systemd_service_setup
  if [ "${WITH_PROXY}" = "true" ]; then
    install_seestar_proxy
  fi
  print_banner "setup"
}

#
# run setup if not sourced from another file
#
(return 0 2>/dev/null) && sourced=1 || sourced=0
if [ ${sourced} = 0 ]; then
  setup
fi
