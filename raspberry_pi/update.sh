#!/bin/bash -e
src_home=$(cd $(dirname $0)/.. && pwd)
source ${src_home}/raspberry_pi/setup.sh

function update() {
  validate_access

  while [ $# -gt 0 ]; do
    case "$1" in
      --force)
        FORCE=true
        shift
        ;;
      --relaunch)
        FORCE=true
        RELAUNCH=true
        shift
        ;;
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
      --proxy-env)
        export WITH_PROXY=true
        _existing=$(printf '%s' "${SEESTAR_PROXY_ENV_B64}" | base64 -d 2>/dev/null || true)
        export SEESTAR_PROXY_ENV_B64=$(printf '%s\n%s' "${_existing}" "$2" | sed '/^$/d' | base64 -w0)
        export SEESTAR_PROXY_CONFIG_DIRTY=true
        shift 2
        ;;
      --help|-h)
        cat <<_EOF
Usage: update.sh [OPTIONS]

Update seestar_alp to the latest version from the remote repository.

Options:
  --force                Force update even if already up-to-date
  --with-proxy           Install/update seestar-proxy alongside seestar_alp.
                         Auto-detected on subsequent runs if already installed.
  --seestar-ip IP        Upstream Seestar IP or hostname for seestar-proxy
                         (default: seestar.local). Rewrites proxy config.
  --proxy-hook PATH      Lua hook script for seestar-proxy. Can be repeated.
                         Rewrites proxy config.
  --proxy-env KEY=VALUE  Environment variable for seestar-proxy (e.g. for Lua
                         hooks). Can be repeated. Writes /etc/seestar-proxy/proxy.env.
                         You may also edit that file directly.
  -h, --help             Show this help message

Examples:
  raspberry_pi/update.sh
  raspberry_pi/update.sh --force
  raspberry_pi/update.sh --with-proxy --seestar-ip 192.168.1.42
  raspberry_pi/update.sh --proxy-hook /home/pi/hooks/authenticate.lua \\
                         --proxy-env KEY_PATH=/home/pi/seestar.pem \\
                         --proxy-env LUA_CPATH=/usr/lib/aarch64-linux-gnu/lua/5.1/?.so
_EOF
        exit 0
        ;;
      *)
        shift
        ;;
    esac
  done

  # Auto-detect proxy if already installed, unless explicitly disabled by the
  # caller.  Reads upstream from the existing config so it is preserved.
  if [ "${WITH_PROXY}" != "true" ] && [ -e /etc/seestar-proxy/config.toml ]; then
    export WITH_PROXY=true
    if [ "${SEESTAR_PROXY_UPSTREAM}" = "seestar.local" ]; then
      detected=$(grep '^upstream' /etc/seestar-proxy/config.toml | sed 's/upstream *= *"\(.*\)"/\1/')
      [ -n "${detected}" ] && export SEESTAR_PROXY_UPSTREAM="${detected}"
    fi
    echo "seestar-proxy detected — will update (upstream: ${SEESTAR_PROXY_UPSTREAM})"
  fi

  # check if update is required
  cd "${src_home}"
  git fetch origin
  if [ $(git rev-parse HEAD) = $(git rev-parse @{u}) ] && [ "${FORCE}" != "true" ]; then
      echo "Nothing to do, you're already up-to-date!"
      exit 0
  fi

  cd ${src_home}
  git pull

  # Update script needs to relaunch itself, to pick up source changes.
  # WITH_PROXY / SEESTAR_PROXY_UPSTREAM are exported so they survive exec.
  if [ -z "${RELAUNCH}" ]; then
    echo "Re-launching update script with new source"
    exec ${src_home}/raspberry_pi/update.sh --relaunch
  fi

  if $(systemctl is-active --quiet seestar); then
    sudo systemctl stop seestar
  fi

  if $(systemctl is-active --quiet INDI); then
    sudo systemctl stop INDI
  fi

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
  network_config
  systemd_service_setup
  if [ "${WITH_PROXY}" = "true" ]; then
    install_seestar_proxy
  fi
  print_banner "update"
}

#
# run update if not sourced from another file
#
(return 0 2>/dev/null) && sourced=1 || sourced=0
if [ ${sourced} = 0 ]; then
    update $@
fi
