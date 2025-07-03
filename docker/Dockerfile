FROM ubuntu:24.04

ARG ASTRO_PLATFORM="ALPACA"

SHELL ["/bin/bash", "-c"]

ENV SEESTAR_USER=ubuntu
ENV SEESTAR_USER_HOME=/home/${SEESTAR_USER}
ENV ROOT=root

###
### Install dependencies.
###
ARG DEBIAN_FRONTEND=noninteractive
ARG TZ=Etc/UTC
RUN apt-get update && \
    apt-get install --yes avahi-utils python3 python3-pip software-properties-common vim git tzdata libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev libgdbm-dev lzma lzma-dev tcl-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev wget curl make build-essential openssl libgl1 && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

USER ${SEESTAR_USER}

ENV SEESTAR_ALP_DIR=${SEESTAR_USER_HOME}/seestar_alp
RUN mkdir ${SEESTAR_ALP_DIR}
WORKDIR ${SEESTAR_ALP_DIR}


COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} ./requirements.txt ${SEESTAR_ALP_DIR}/requirements.txt

RUN python3 -m pip install --break-system-packages -U pip && \
    python3 -m pip install --break-system-packages -r requirements.txt


COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} . ${SEESTAR_ALP_DIR}
COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} ./docker/entrypointALPACA.sh ${SEESTAR_ALP_DIR}/entrypointALPACA.sh
COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} ./docker/entrypointINDI.sh ${SEESTAR_ALP_DIR}/entrypointINDI.sh

USER $ROOT

RUN if [ "$ASTRO_PLATFORM" = "ALPACA" ]; then \
		mv ${SEESTAR_ALP_DIR}/entrypointALPACA.sh ${SEESTAR_USER_HOME}/entrypoint.sh; \
	else \
		apt-add-repository ppa:mutlaqja/ppa && \ 
		apt-get install -y indi-bin && \
		rm -rf /var/lib/apt/lists/* && \
		apt-get clean && \
		pip install git+https://github.com/MMTObservatory/pyINDI.git && \
		mv ${SEESTAR_ALP_DIR}/entrypointINDI.sh ${SEESTAR_USER_HOME}/entrypoint.sh; \
	fi
	
USER ${SEESTAR_USER}

# use bash if you want to debug the container
# ENTRYPOINT ["/bin/bash"]
ENTRYPOINT ${SEESTAR_USER_HOME}"/entrypoint.sh"
