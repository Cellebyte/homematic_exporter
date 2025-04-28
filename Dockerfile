<<<<<<< HEAD
FROM --platform=$BUILDPLATFORM docker.io/library/python:3.11-bookworm as build
ARG TARGETPLATFORM
ARG BUILDPLATFORM
WORKDIR /workspace
COPY . . 
RUN pip3 install poetry
RUN poetry build

FROM docker.io/library/python:3.13-slim-bookworm
COPY --from=build /workspace/dist/ /tmp/
RUN pip3 --no-cache-dir install /tmp/*.tar.gz
RUN rm -rf /tmp/*
RUN apt-get update && apt-get install curl -y
COPY healthcheck.sh /usr/local/bin/healthcheck.sh

ENTRYPOINT [ "/usr/local/bin/homematic_exporter" ]

EXPOSE 8010
HEALTHCHECK --interval=20s --timeout=3s \
    CMD bash /usr/local/bin/healthcheck.sh
