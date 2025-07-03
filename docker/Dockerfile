FROM python:3.12-slim

ARG ASTRO_PLATFORM="ALPACA"

SHELL ["/bin/bash", "-c"]

# Create a group and user
RUN addgroup appuser --gid 1000 && adduser appuser --gid 1000 --uid 1000

ENV SEESTAR_USER=appuser
ENV SEESTAR_USER_HOME=/home/${SEESTAR_USER}
ENV ROOT=root

###
### Install dependencies.
###
ARG DEBIAN_FRONTEND=noninteractive
ARG TZ=Etc/UTC
RUN apt-get update && \
    apt-get install --yes avahi-utils software-properties-common vim git tzdata libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev libgdbm-dev lzma lzma-dev tcl-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev wget curl make build-essential openssl libgl1

USER ${SEESTAR_USER}

ENV SEESTAR_ALP_DIR=${SEESTAR_USER_HOME}/seestar_alp
RUN mkdir ${SEESTAR_ALP_DIR}
WORKDIR ${SEESTAR_ALP_DIR}


COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} ./requirements.txt ${SEESTAR_ALP_DIR}/requirements.txt

# Create a virtual environment
RUN python3 -m venv ${SEESTAR_USER_HOME}/venv

# Add the venv's bin to the PATH.
# This makes "python" and "pip" automatically use the venv's versions.
ENV PATH="${SEESTAR_USER_HOME}/venv/bin:$PATH"

RUN python3 -m pip install --no-cache-dir -r requirements.txt


COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} . ${SEESTAR_ALP_DIR}
COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} ./docker/entrypointALPACA.sh ${SEESTAR_ALP_DIR}/entrypointALPACA.sh
COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} ./docker/entrypointINDI.sh ${SEESTAR_ALP_DIR}/entrypointINDI.sh

USER $ROOT

RUN if [ "$ASTRO_PLATFORM" = "ALPACA" ]; then \
		mv ${SEESTAR_ALP_DIR}/entrypointALPACA.sh ${SEESTAR_USER_HOME}/entrypoint.sh; \
	else \
		apt-add-repository ppa:mutlaqja/ppa && \ 
		apt-get install -y indi-bin && \
		pip install --no-cache-dir git+https://github.com/MMTObservatory/pyINDI.git && \
		mv ${SEESTAR_ALP_DIR}/entrypointINDI.sh ${SEESTAR_USER_HOME}/entrypoint.sh; \
	fi

# Clean up apt cache to reduce image size
RUN apt-get clean && rm -rf /var/lib/apt/lists/* 

USER ${SEESTAR_USER}

# use bash if you want to debug the container
# ENTRYPOINT ["/bin/bash"]
ENTRYPOINT ${SEESTAR_USER_HOME}"/entrypoint.sh"
