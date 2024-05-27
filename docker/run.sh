#!/usr/bin/env bash

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
SCRIPT_NAME="${0}"

SEESTAR_ALP_REGISTRY=docker.io/library

SEESTAR_ALP_IMAGE_NAME=seestar_alp
SEESTAR_ALP_IMAGE_VERSION=latest
SEESTAR_ALP_IMAGE_FULL=${SEESTAR_ALP_REGISTRY}/${SEESTAR_ALP_IMAGE_NAME}:${SEESTAR_ALP_IMAGE_VERSION}

# Arguments
DOCKER_BUILD_IMAGE="false"

source "${SCRIPT_DIR}/util.sh"


define_usage() {
    local -n define_usage_SCRIPT_NAME="${1:?}"

    read -d '' USAGE <<EOM

Usage: ${define_usage_SCRIPT_NAME} [OPTIONS]

Options:
    -b, --build     Build the image before running.
    -h, --help      Print help and exit.

EOM
}

parse_args() {
    local OPTIND

    while getopts_long "bh build help" option "${@}"; do
        case "${option}" in
            "b" | "build")
                DOCKER_BUILD_IMAGE="true"
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
        "${SCRIPT_DIR}/../"

    if [ ! -f "${SCRIPT_DIR}/config.toml" ]; then
        echo "S{SCRIPT_DIR}/config.toml doesn't exist.  Copy and customize ${SCRIPT_DIR}/config.toml.example."
        return 1
    fi

    read -d '' DOCKER_RUN_OPTIONS <<EOM
        --mount type=bind,source="${SCRIPT_DIR}/config.toml",target="/home/seestar/seestar_alp/device/config.toml" \
        -p 5555:5555
EOM

    docker_run \
        SEESTAR_ALP_IMAGE_NAME \
        SEESTAR_ALP_IMAGE_FULL \
        DOCKER_RUN_OPTIONS
}

# Setup
setup SCRIPT_DIR SCRIPT_NAME

# Parse arguments
parse_args "${@}"
shift $(( OPTIND - 1 ))

# Main
main
