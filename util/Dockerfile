FROM almalinux:8.7

RUN rpm --import https://repo.almalinux.org/almalinux/RPM-GPG-KEY-AlmaLinux
RUN yum install -y python3.11 wget git unzip
RUN python3.11 -m ensurepip
RUN pip3.11 install --upgrade pip
RUN pip3.11 install --upgrade setuptools
RUN pip3.11 install --upgrade wheel

