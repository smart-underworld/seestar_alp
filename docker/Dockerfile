FROM ubuntu:22.04

###
### Create seestar user.
###

ARG SEESTAR_UID=1000
ENV SEESTAR_UID=${SEESTAR_UID}
ARG SEESTAR_GID=1000
ENV SEESTAR_GID=${SEESTAR_GID}

SHELL ["/bin/bash", "-c"]

ENV SEESTAR_USER=seestar
ENV SEESTAR_USER_HOME=/home/seestar

RUN groupadd -g ${SEESTAR_UID} ${SEESTAR_USER} && \
    useradd ${SEESTAR_USER} -u ${SEESTAR_UID} -g ${SEESTAR_GID} -r -m -d ${SEESTAR_USER_HOME} -s /bin/bash

###
### Install dependencies.
###
ARG DEBIAN_FRONTEND=noninteractive
ARG TZ=Etc/UTC
RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
        vim \
        tzdata && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

USER ${SEESTAR_USER}

ENV SEESTAR_ALP_DIR=${SEESTAR_USER_HOME}/seestar_alp
RUN mkdir ${SEESTAR_ALP_DIR}
WORKDIR ${SEESTAR_ALP_DIR}

COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} . ${SEESTAR_ALP_DIR}

RUN python3 -m pip install -U pip && \
    python3 -m pip install -r requirements.txt

COPY --chown=${SEESTAR_USER}:${SEESTAR_USER} ./docker/entrypoint.sh ${SEESTAR_USER_HOME}/entrypoint.sh

ENTRYPOINT ["/home/seestar/entrypoint.sh"]
