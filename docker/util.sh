#!/usr/bin/env bash

docker_build() {
    local -n docker_build_BUILD="${1:?}"
    local docker_build_PROGRESS="${2:?}"
    local docker_build_DOCKERFILE_PATH="${3:?}"
    local -n docker_build_IMAGE_NAME="${4:?}"
    local -n docker_build_ASTRO_PLATFORM="${5:?}"
    local docker_build_CONTEXT_PATH="${6:?}"

    # Build if the image doesn't exist or if requested.
    if [ "${docker_build_BUILD}" != "true" ]; then
        if [ ! -z "$(docker inspect "${docker_build_IMAGE_NAME}" > /dev/null 2>&1)" ]; then
            return 0
        fi
    fi

    if [ "${docker_build_PROGRESS}" == "true" ]; then
        docker_build_PROGRESS="--progress plain"
    else
        docker_build_PROGRESS=""
    fi

    read -d '' DOCKER_BUILD_COMMAND <<EOM
docker build \
    ${docker_build_PROGRESS} \
    -f "${docker_build_DOCKERFILE_PATH}" \
    --build-arg ASTRO_PLATFORM=${docker_build_ASTRO_PLATFORM} \
    -t "${docker_build_IMAGE_NAME}" \
    "${docker_build_CONTEXT_PATH}"
EOM

    eval "${DOCKER_BUILD_COMMAND}"
}

docker_run() {
    local -n docker_run_IMAGE_NAME="${1:?}"
    local -n docker_run_IMAGE_FULL="${2:?}"
    local time_zone="${3:?}"

    read -d '' DOCKER_RUN_COMMAND <<EOM
docker run -it --rm \
    --name "${docker_run_IMAGE_NAME}" \
    -e "TZ=${time_zone}" \
    ${DOCKER_RUN_OPTIONS} \
    "${docker_run_IMAGE_FULL}"
EOM

    eval "${DOCKER_RUN_COMMAND}"
}

help_exit() {
    local help_exit_REQUESTED="${1:?}"

    echo "${USAGE}"

    if [ "${help_exit_REQUESTED}" == "true" ]; then
        exit 0
    fi

    exit 1
}

install_getopts_long() {
    local -n install_getopts_long_SCRIPT_DIR=${1:?}

    if [ ! -d "${install_getopts_long_SCRIPT_DIR}/getopts_long" ]; then
        git clone https://github.com/UrsaDK/getopts_long.git "${install_getopts_long_SCRIPT_DIR}/getopts_long"
    fi

    source "${install_getopts_long_SCRIPT_DIR}/getopts_long/lib/getopts_long.bash"
}

setup() {
    local -n setup_SCRIPT_DIR="${1:?}"
    local -n setup_SCRIPT_NAME="${2:?}"

    define_usage setup_SCRIPT_NAME
    install_getopts_long setup_SCRIPT_DIR
}
