#!/usr/bin/env python3

import argparse
import logging
import threading
from http.server import HTTPServer
from pprint import pformat
from socketserver import ThreadingMixIn

from prometheus_client import MetricsHandler
from prometheus_client.core import REGISTRY
from pyccu3 import PyCCU3Legacy  #

from homematic_exporter.collectors.legacy import HomeMaticLegacyCollector
from homematic_exporter.collectors.xml_api import HomeMaticCollector


class _ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    """Thread per request HTTP server."""


def start_http_server(port, registry, addr=""):
    """Starts an HTTP server for prometheus metrics as a daemon thread"""
    httpd = _ThreadingSimpleServer((addr, port), MetricsHandler.factory(registry))
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = False
    thread.start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ccu_host", help="The hostname of the ccu instance", required=True
    )
    parser.add_argument(
        "--ccu_port",
        help="The port for the xmlrpc service (2001 for BidcosRF, 2010 for HmIP)",
        default=2010,
    )
    parser.add_argument(
        "--ccu_user", help="The username for the CCU (if authentication is enabled)"
    )
    parser.add_argument(
        "--ccu_pass", help="The password for the CCU (if authentication is enabled)"
    )
    parser.add_argument("--ccu_session_id", help="The session-id for the XML-API")
    parser.add_argument(
        "--interval",
        help="The interval between two gathering runs in seconds",
        default=60,
    )
    parser.add_argument(
        "--namereload",
        help="After how many intervals the device names are reloaded",
        default=30,
    )
    parser.add_argument(
        "--port", help="The port where to expose the exporter", default=8010
    )
    parser.add_argument(
        "--config_file",
        help="A config file with e.g. supported types and device name mappings",
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--dump_devices",
        help="Do not start exporter, just dump device list",
        action="store_true",
    )
    parser.add_argument(
        "--dump_parameters",
        help="Do not start exporter, just dump device parameters of given device",
    )
    parser.add_argument(
        "--dump_device_names",
        help="Do not start exporter, just dump device names",
        action="store_true",
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
        )
    else:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )

    auth = (
        (args.ccu_user, args.ccu_pass)
        if args.ccu_user and args.ccu_pass
        else (None, args.ccu_session_id)
        if args.ccu_session_id
        else (None, None)
    )

    if (
        args.dump_devices
        or args.dump_parameters
        or args.dump_device_names
        and not args.ccu_session_id
    ):
        with PyCCU3Legacy(
            args.ccu_host, username=auth[0], password=auth[1], port=args.ccu_port
        ) as ccu3:
            if args.dump_devices:
                print(pformat(ccu3.devices))
            elif args.dump_device_names:
                print(pformat(ccu3.device_names()))
            elif args.dump_parameters:
                print("PARAMSET_DESCRIPTION:")
                print(
                    pformat(ccu3.paramset_description(args.dump_parameters, "VALUES"))
                )
                print("PARAMSET:")
                print(pformat(ccu3.paramset(args.dump_parameters, "VALUES")))
    else:
        if not args.ccu_session_id:
            REGISTRY.register(
                HomeMaticLegacyCollector(
                    host=args.ccu_host,
                    port=args.ccu_port,
                    auth=auth,
                    config_filename=args.config_file,
                )
            )
        else:
            REGISTRY.register(
                HomeMaticCollector(
                    args.ccu_host,
                    auth=auth,
                    verify=False,
                )
            )
        # Start up the server to expose the metrics.
        logging.info(f"Exposing metrics on port {args.port}")
        start_http_server(int(args.port), registry=REGISTRY)
