FROM --platform=$BUILDPLATFORM docker.io/library/python:3.11-bookworm as build
ARG TARGETPLATFORM
ARG BUILDPLATFORM
WORKDIR /workspace
COPY . . 
RUN pip3 install poetry
RUN poetry build

FROM docker.io/library/python:3.11-slim-bookworm
COPY --from=build /workspace/dist/ /tmp/
RUN pip3 install /tmp/*.tar.gz
RUN rm -rf /tmp/*

ENTRYPOINT [ "/usr/local/bin/homematic_exporter" ]

EXPOSE 8010
