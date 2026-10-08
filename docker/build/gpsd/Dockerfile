FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       gpsd gpsd-clients socat python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/gpsd
COPY start-gpsd.sh healthcheck.py ./
RUN chmod +x start-gpsd.sh

ENTRYPOINT ["/bin/bash", "/opt/gpsd/start-gpsd.sh"]
