#!/usr/bin/env bash

REPO=ghcr.io/cellebyte/homematic_exporter
podman build --platform linux/amd64 --platform linux/arm/v7 --platform linux/arm64 -t $REPO:"$(date +%F)" -t $REPO:latest  .
