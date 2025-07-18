FROM python:3.11

RUN python3.11 -m ensurepip
# RDH disabled due to podman / overlayfs compat issues as of 2025-07-18
# RUN pip3.11 install --upgrade pip
RUN pip3.11 install --upgrade setuptools
RUN pip3.11 install --upgrade wheel
RUN /source/util/build.sh