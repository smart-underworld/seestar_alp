#!/usr/bin/env bash

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
SCRIPT_NAME="${0}"

SEESTAR_ALP_REGISTRY=docker.io/library

SEESTAR_ALP_IMAGE_NAME=seestar_alp
SEESTAR_ALP_IMAGE_VERSION=latest
SEESTAR_ALP_IMAGE_FULL=${SEESTAR_ALP_REGISTRY}/${SEESTAR_ALP_IMAGE_NAME}:${SEESTAR_ALP_IMAGE_VERSION}

# Arguments
DOCKER_BUILD_IMAGE="false"
ASTRO_PLATFORM="ALPACA"

# Set local time zone - choose from TZ identifier listed at
# https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
if [ -z "${TIME_ZONE}" ]; then TIME_ZONE="America/Vancouver"; fi

source "${SCRIPT_DIR}/util.sh"


define_usage() {
    local -n define_usage_SCRIPT_NAME="${1:?}"

    read -d '' USAGE <<EOM

Usage: ${define_usage_SCRIPT_NAME} [OPTIONS]

Options:
    -t <TZ>, --timezone=<TZ>    Set the timezone (default: ${TIME_ZONE})
    -i, --indi                  Enable INDI server.
    -b, --build                 Build the image before running.
    -h, --help                  Print help and exit.

EOM
}

parse_args() {
    local OPTIND

    while getopts_long "biht: build indi help timezone:" option "${@}"; do
        case "${option}" in
            "t" | "timezone")
                TIME_ZONE=${OPTARG}
                echo "TIME_ZONE set to ${TIME_ZONE}"
                ;;
            "i" | "indi")
            	ASTRO_PLATFORM="INDI"
            	echo "INDI support enabled"
            	;;
            "b" | "build")
                DOCKER_BUILD_IMAGE="true"
                echo "Docker build enabled"
                ;;
            "h" | "help")
                help_exit "true"
                ;;
            "?")
                echo "Error: invalid option (${OPTARG})."
                help_exit "false"
                ;;
            ":")
                echo "Error: -${OPTARG} requires an argument."
                help_exit "false"
                ;;
            *)
                help_exit "false"
                ;;
        esac
    done
    shift $(( OPTIND - 1 ))
}


main() {
    docker_build \
        DOCKER_BUILD_IMAGE \
        "true" \
        "${SCRIPT_DIR}/Dockerfile" \
        SEESTAR_ALP_IMAGE_FULL \
        ASTRO_PLATFORM \
        "${SCRIPT_DIR}/../"

    if [ ! -f "${SCRIPT_DIR}/config.toml" ]; then
        cp ${SCRIPT_DIR}/config.toml.example ${SCRIPT_DIR}/config.toml
    fi

    if [ -z "${TIME_ZONE}" ]; then
        echo "TIME_ZONE has not been set - see arguments in run.sh"
        return 1
    fi

    # config options
    CONFIG_OPTION="--mount type=bind,source=\"${SCRIPT_DIR}/config.toml\",target=\"/home/seestar/seestar_alp/device/config.toml\""

    if [[ "$(uname -s)" == "Linux" ]]; then
        # For Linux, we can use host networking and bind mount D-Bus and Avahi sockets - this lets mDNS work from inside the guest
        read -d '' DOCKER_RUN_OPTIONS <<EOM
        ${CONFIG_OPTION} \
        --network host \
        -v /var/run/dbus:/var/run/dbus \
        -v /var/run/avahi-daemon/socket:/var/run/avahi-daemon/socket
EOM
    else
        # For macOS and Windows, we do the old-school slirp based networking (and I bet mDNS won't work)
        read -d '' DOCKER_RUN_OPTIONS <<EOM
        ${CONFIG_OPTION} \
        -p 5432:5432 \
        -p 5555:5555 \
        -p 7624:7624 \
        -p 7556:7556
EOM
    fi

    docker_run \
        SEESTAR_ALP_IMAGE_NAME \
        SEESTAR_ALP_IMAGE_FULL \
        "${TIME_ZONE}" \
        DOCKER_RUN_OPTIONS
}

# Setup
setup SCRIPT_DIR SCRIPT_NAME

# Parse arguments
parse_args "${@}"
shift $(( OPTIND - 1 ))

# Main
main
