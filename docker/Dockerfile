FROM ubuntu:24.04

ARG ASTRO_PLATFORM="ALPACA"

###
### Create seestar user.
###

ARG SEESTAR_UID=1001
ENV SEESTAR_UID=${SEESTAR_UID}
ARG SEESTAR_GID=1001
ENV SEESTAR_GID=${SEESTAR_GID}

SHELL ["/bin/bash", "-c"]

ENV SEESTAR_USER=seestar
ENV SEESTAR_USER_HOME=/home/seestar
ENV ROOT=root

RUN groupadd -g ${SEESTAR_UID} ${SEESTAR_USER} && \
    useradd ${SEESTAR_USER} -u ${SEESTAR_UID} -g ${SEESTAR_GID} -r -m -d ${SEESTAR_USER_HOME} -s /bin/bash

###
### Install dependencies.
###
ARG DEBIAN_FRONTEND=noninteractive
ARG TZ=Etc/UTC
RUN apt-get update && \
    apt-get install --yes python3 python3-pip software-properties-common vim git tzdata libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev libgdbm-dev lzma lzma-dev tcl-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev wget curl make build-essential openssl libgl1 && \
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

ENTRYPOINT ["/home/seestar/entrypoint.sh"]
