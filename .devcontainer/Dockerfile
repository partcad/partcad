FROM ghcr.io/hadolint/hadolint:v2.12.1-beta-debian as hadolint

FROM mcr.microsoft.com/devcontainers/python:3.10-bookworm

COPY --from=hadolint /bin/hadolint /usr/local/bin/hadolint

RUN \
  --mount=type=bind,source=./apt.txt,target=/tmp/apt.txt \
  --mount=type=bind,source=./apt.sh,target=/tmp/apt.sh \
  /tmp/apt.sh
