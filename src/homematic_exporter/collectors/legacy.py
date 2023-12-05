import json
import logging
import xmlrpc
from pprint import pformat
from typing import Dict, Iterable, Optional

from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from pyccu3 import PyCCU3Legacy
from pyccu3.constants import CHANNELS_WITH_ERRORS_ALLOWED, SUPPORTED_DEVICE_TYPES
from pyccu3.objects.legacy import HomeMaticRPCDevice

from homematic_exporter.cache import ttl_lru_cache


class HomeMaticLegacyCollector(Collector):
    namespace = "homematic"
    # Supported Homematic (BidcosRF and IP) device types

    auth = None
    reload_names_active = False
    mapped_names: Dict[str, str] = {}
    metrics: Dict[str, GaugeMetricFamily] = {}
    supported_device_types = SUPPORTED_DEVICE_TYPES
    channels_with_errors_allowed = CHANNELS_WITH_ERRORS_ALLOWED

    def __init__(self, host, port, auth, config_filename: Optional[str] = None):
        super().__init__()
        self.client = PyCCU3Legacy(
            host=host, username=auth[0], password=auth[1], port=port
        )
        self.host = host
        self.default_mapped_names = True
        self.logger = logging.getLogger(self.__class__.__name__)
        if config_filename:
            with open(config_filename) as config_file:
                self.logger.info("Processing config file {}".format(config_filename))
                config = json.load(config_file)
                self.default_mapped_names = False
                self.mapped_names = config.get("device_mapping", {})
                self.supported_device_types = config.get(
                    "supported_device_types", SUPPORTED_DEVICE_TYPES
                )
                self.channels_with_errors_allowed = config.get(
                    "channels_with_errors_allowed", CHANNELS_WITH_ERRORS_ALLOWED
                )

    def generate_metrics(self):
        self.logger.info("Gathering metrics")
        devices = self.client.devices
        self.metrics["devicecount"] = GaugeMetricFamily(
            f"{self.namespace}_devicecount",
            "Number of processed/supported devices",
            labels=("ccu",),
        )
        self.metrics["devicecount"].add_metric((self.host,), float(len(devices)))
        for device in devices:
            if device.parent == "":
                if device.type in self.supported_device_types:
                    devChildcount = len(device.children)
                    self.logger.info(
                        "Found top-level device {} of type {} with {} children".format(
                            device.address, device.type, devChildcount
                        )
                    )
                    self.logger.debug(pformat(device))
                else:
                    self.logger.info(
                        "Found unsupported top-level device {} of type {}".format(
                            device.address, device.type
                        )
                    )
            if device.parent_type in self.supported_device_types:
                self.logger.debug(
                    "Found device {} of type {} in supported parent type {}".format(
                        device.address, device.type, device.parent_type
                    )
                )
                self.logger.debug(pformat(device))

                allowFailedChannel = False
                invalidChannels = self.channels_with_errors_allowed.get(
                    device.parent_type
                )
                if invalidChannels is not None:
                    channel = int(device.address[device.address.find(":") + 1 :])
                    if channel in invalidChannels:
                        allowFailedChannel = True

                if "VALUES" in device.paramsets:
                    paramset = {}
                    try:
                        paramset = self.client.paramset(device.address, "VALUES")
                    except xmlrpc.client.Fault:
                        if allowFailedChannel:
                            self.logger.debug(
                                "Error reading paramset for device {} of type {} in parent type {} (expected)".format(
                                    device.address, device.type, device.parent_type
                                )
                            )
                        else:
                            self.logger.debug(
                                "Error reading paramset for device {} of type {} in parent type {} (unexpected)".format(
                                    device.address, device.type, device.parent_type
                                )
                            )
                            raise
                    paramsetDescription = self.client.paramset_description(
                        device.address, "VALUES"
                    )
                    for key in paramsetDescription:
                        paramDesc = paramsetDescription.get(key)
                        paramType = paramDesc.get("TYPE")
                        if paramType in ["FLOAT", "INTEGER", "BOOL"]:
                            self.process_single_value(
                                device, paramType, key, paramset.get(key)
                            )
                        elif paramType == "ENUM":
                            self.logger.debug(
                                "Found {}: desc: {} key: {}".format(
                                    paramType, paramDesc, paramset.get(key)
                                )
                            )
                            self.process_enum(
                                device,
                                key,
                                paramset.get(key),
                                paramDesc.get("VALUE_LIST"),
                            )
                        else:
                            # ATM Unsupported like HEATING_CONTROL_HMIP.PARTY_TIME_START,
                            # HEATING_CONTROL_HMIP.PARTY_TIME_END, COMBINED_PARAMETER or ACTION
                            self.logger.debug(
                                "Unknown paramType {}, desc: {}, key: {}".format(
                                    paramType, paramDesc, paramset.get(key)
                                )
                            )

                    if paramset:
                        self.logger.debug(
                            "ParamsetDescription for {}".format(device.address)
                        )
                        self.logger.debug(pformat(paramsetDescription))
                        self.logger.debug("Paramset for {}".format(device.address))
                        self.logger.debug(pformat(paramset))

    @ttl_lru_cache(3600)
    def get_mappings(self):
        if self.default_mapped_names:
            return {
                mapping["address"]: mapping.get("name", "unknown")
                for mapping in self.client.device_names()
            }

    def resolve_mapped_name(self, device: HomeMaticRPCDevice):
        mapped_names = self.get_mappings()
        if device.address in mapped_names.keys() and not device.default_device:
            return mapped_names[device.address]
        elif device.parent in mapped_names.keys():
            return mapped_names[device.parent]
        else:
            return device.address

    def process_single_value(self, device: HomeMaticRPCDevice, paramType, key, value):
        self.logger.debug(
            "Found {} param {} with value {}".format(paramType, key, value)
        )

        if value == "" or value is None:
            return
        gaugename = key.lower()
        if not gaugename in self.metrics:
            self.metrics[gaugename] = GaugeMetricFamily(
                f"{self.namespace}_{gaugename}",
                "Metrics for " + key,
                labels=(
                    "ccu",
                    "device",
                    "device_type",
                    "parent_device_type",
                    "mapped_name",
                ),
            )
        self.metrics[gaugename].add_metric(
            (
                self.host,
                device.address,
                device.type,
                device.parent_type,
                self.resolve_mapped_name(device),
            ),
            float(value),
        )

    def process_enum(self, device: HomeMaticRPCDevice, key, value, istates):
        if value == "" or value is None:
            self.logger.debug(
                "Skipping processing enum {} with empty value".format(key)
            )
            return

        gaugename = key.lower() + "_set"
        self.logger.debug(
            "Found enum param {} with value {}, gauge {}".format(key, value, gaugename)
        )
        if not gaugename in self.metrics:
            self.metrics[gaugename] = GaugeMetricFamily(
                f"{self.namespace}_{gaugename}",
                "Metrics for " + key,
                labels=[
                    "ccu",
                    "device",
                    "device_type",
                    "parent_device_type",
                    "mapped_name",
                    "state",
                ],
            )
        mapped_name_v = self.resolve_mapped_name(device)
        state = istates[int(value)]
        self.logger.debug(
            "Setting {} to value {}/{}".format(mapped_name_v, str(value), state)
        )

        for istate in istates:
            self.metrics[gaugename].add_metric(
                (
                    self.host,
                    device.address,
                    device.type,
                    device.parent_type,
                    mapped_name_v,
                    istate,
                ),
                int(state == istate),
            )

    def collect(self) -> Iterable[Metric]:
        self.generate_metrics()
        for value in self.metrics.values():
            yield value
        self.metrics = {}
        return super().collect()
