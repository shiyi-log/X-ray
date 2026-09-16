FROM debian:13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates jq shellcheck unzip util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY installer/ installer/
ENTRYPOINT ["bash"]
