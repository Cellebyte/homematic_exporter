FROM --platform=$BUILDPLATFORM docker.io/library/python:3.13-bookworm as build
ARG TARGETPLATFORM
ARG BUILDPLATFORM
WORKDIR /workspace
COPY . . 
RUN pip3 install poetry poetry-plugin-export
RUN poetry build
Run poetry export -f requirements.txt --output ./dist/requirements.txt

FROM docker.io/library/python:3.13-slim-bookworm
COPY --from=build /workspace/dist/ /tmp/
RUN pip3 install --no-cache-dir --no-deps -r /tmp/requirements.txt && pip3 install --no-cache-dir --no-deps /tmp/*.tar.gz
RUN rm -rf /tmp/*

ENTRYPOINT [ "/usr/local/bin/homematic_exporter" ]

EXPOSE 8010
