ARG POSTGRES_IMAGE=postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94
FROM ${POSTGRES_IMAGE}

ARG TARGETARCH
ARG AGE_VERSION=1.2.1
ARG AGE_AMD64_SHA256=7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50
ARG AGE_ARM64_SHA256=57fd79a7ece5fe501f351b9dd51a82fbee1ea8db65a8839db17f5c080245e99f
ARG JQ_VERSION=1.8.1
ARG JQ_AMD64_SHA256=020468de7539ce70ef1bceaf7cde2e8c4f2ca6c3afb84642aabc5c97d9fc2a0d
ARG JQ_ARM64_SHA256=6bc62f25981328edd3cfcfe6fe51b073f2d7e7710d7ef7fcdac28d4e384fc3d4

RUN target_arch="${TARGETARCH:-$(uname -m)}" \
    && case "$target_arch" in \
      amd64|x86_64) target_arch="amd64"; age_sha="$AGE_AMD64_SHA256"; jq_sha="$JQ_AMD64_SHA256" ;; \
      arm64|aarch64) target_arch="arm64"; age_sha="$AGE_ARM64_SHA256"; jq_sha="$JQ_ARM64_SHA256" ;; \
      *) echo "unsupported target architecture: $target_arch" >&2; exit 1 ;; \
    esac \
    && age_asset="age-v${AGE_VERSION}-linux-${target_arch}.tar.gz" \
    && wget -q -O /tmp/age.tgz \
      "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/${age_asset}" \
    && echo "$age_sha  /tmp/age.tgz" | sha256sum -c - \
    && tar -xzf /tmp/age.tgz -C /tmp \
    && cp "/tmp/age/age" "/tmp/age/age-keygen" /usr/local/bin/ \
    && wget -q -O /usr/local/bin/jq \
      "https://github.com/jqlang/jq/releases/download/jq-${JQ_VERSION}/jq-linux-${target_arch}" \
    && echo "$jq_sha  /usr/local/bin/jq" | sha256sum -c - \
    && chmod 0555 /usr/local/bin/age /usr/local/bin/age-keygen /usr/local/bin/jq \
    && age --version | grep -F "${AGE_VERSION}" \
    && jq --version | grep -F "jq-${JQ_VERSION}" \
    && pg_dump --version | grep -F "17.6" \
    && rm -rf /tmp/age /tmp/age.tgz

LABEL org.opencontainers.image.title="X-ray backup tools" \
      org.opencontainers.image.version="postgres-17.6_age-1.2.1_jq-1.8.1"

WORKDIR /workspace
ENTRYPOINT []
CMD ["/bin/sh"]
