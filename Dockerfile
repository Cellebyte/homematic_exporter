FROM python:3.11-bookworm as build
WORKDIR /workspace
COPY . . 
RUN pip3 install poetry
RUN poetry build

FROM python:3.11-slim-bookworm
COPY --from=build /workspace/dist/ /tmp/
RUN ls /tmp
RUN pip3 install /tmp/*.tar.gz
RUN rm -rf /tmp/*

ENTRYPOINT [ "/usr/local/bin/homematic_exporter" ]

EXPOSE 8010
