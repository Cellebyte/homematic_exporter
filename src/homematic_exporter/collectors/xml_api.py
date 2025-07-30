from ipaddress import IPv4Address, IPv6Address
import logging
from typing import Dict, Iterable, Optional, Tuple, Union

from prometheus_client.core import (  # ignore
    CounterMetricFamily,
    GaugeMetricFamily,
    Metric,
)
from prometheus_client.registry import Collector
from pyccu3 import PyCCU3
from pyccu3.objects.xml_api import PartyDate
from pyccu3.enums import BOOLEAN, DataPointType, DataPointUnit

from homematic_exporter.cache import ttl_lru_cache


def floatify(value: Union[float, BOOLEAN, IPv6Address, IPv4Address, PartyDate]) -> float:
    match value:
        case int() | float():
            return float(value)
        case BOOLEAN.TRUE:
            return float(1.0)
    return float(0.0)


class HomeMaticCollector(Collector):
    namespace = "homematic"

    def __init__(
        self,
        host: str,
        auth: Tuple[Optional[str], Optional[str]] = (None, None),
        verify: bool = True,
    ):
        self.host = host
        assert len(auth) > 2, "Please provide a valid session_id"
        self.client = PyCCU3(self.host, session_id=auth[1], verify=verify)
        self.logger = logging.getLogger(self.__class__.__name__)

    @ttl_lru_cache(3600)
    def rooms(self):
        return [room for room in self.client.roomlist().roomList.room]

    @ttl_lru_cache(3100)
    def functions(self):
        return [func for func in self.client.functionlist().functionList.function]

    @ttl_lru_cache(3200)
    def devices(self):
        return [device for device in self.client.devicelist().deviceList.device]

    @ttl_lru_cache(60)
    def get_room_of_device(self, ise_id: int):
        found = [
            room
            for room in self.rooms()
            for channel in room.channel
            if channel.ise_id == ise_id
        ]
        if found and len(found) == 1:
            return found[0].name
        return "unknown"

    @ttl_lru_cache(100)
    def get_device_address_of_device(self, ise_id: int):
        found = [
            device
            for device in self.devices()
            for channel in device.channel
            if channel.ise_id == ise_id
        ]
        if found and len(found) == 1:
            return found[0].address, found[0].device_type
        return "unknown", "unknown"

    @ttl_lru_cache(94)
    def get_function_of_device(self, ise_id: int):
        found = [
            func
            for func in self.functions()
            for channel in func.channel
            if channel.ise_id == ise_id
        ]
        if found and len(found) == 1:
            return found[0].name
        return "unknown"

    def collect(self) -> Iterable[Metric]:
        labels = [
            "ccu",
            "device_name",
            "device_address",
            "device_type",
            "channel_name",
            "room",
            "function",
        ]
        metrics: Dict[str, Union[CounterMetricFamily, GaugeMetricFamily]] = {
            "rssi": GaugeMetricFamily(
                f"{self.namespace}_rssi",
                "The RSSI value from either ccu to device or device to ccu",
                labels=(labels + ["direction"]),
                unit="dbm",
            ),
            "temperature": GaugeMetricFamily(
                f"{self.namespace}_temperature",
                "The Temperature of a Sensor in Celsius",
                labels=labels,
                unit="celsius",
            ),
            "humidity": GaugeMetricFamily(
                f"{self.namespace}_humidity",
                "The measure humidity of a Sensor from 0-1",
                labels=labels,
                unit="ratio",
            ),
            "battery": GaugeMetricFamily(
                f"{self.namespace}_battery",
                "The battery voltage of the device 0 means no battery installed",
                labels=labels,
                unit="volts",
            ),
            "level": GaugeMetricFamily(
                f"{self.namespace}_level",
                "The level of blinds or heating circuits from 0-1 [0(CLOSED)/1(OPEN)]",
                labels=labels,
                unit="ratio",
            ),
            "energy": CounterMetricFamily(
                f"{self.namespace}_energy",
                "The energy consumed by the device.",
                labels=labels,
                unit="joules",
            ),
            "current": GaugeMetricFamily(
                f"{self.namespace}_circuit",
                "The current currently flowing through the circuit",
                labels=labels,
                unit="amperes",
            ),
            "voltage": GaugeMetricFamily(
                f"{self.namespace}_circuit",
                "The voltage currently between the potentials of the circuit",
                labels=labels,
                unit="volts",
            ),
            "power": GaugeMetricFamily(
                f"{self.namespace}_circuit",
                "The radiant flux in the circuit",
                labels=labels,
                unit="joules_per_second",
            ),
        }
        states = self.client.statelist()
        for device in states.stateList.device:
            for channel in device.channel:
                device_address, device_type = self.get_device_address_of_device(
                    channel.ise_id
                )
                room = self.get_room_of_device(channel.ise_id)
                func = self.get_function_of_device(channel.ise_id)
                base_labels = [
                    self.host,
                    device.name,
                    device_address,
                    device_type,
                    channel.name,
                    room,
                    func,
                ]
                for datapoint in channel.datapoint:
                    match datapoint.type:
                        case DataPointType.RSSI_DEVICE | DataPointType.RSSI_PEER:
                            direction = (
                                "device->ccu"
                                if datapoint.type == DataPointType.RSSI_PEER
                                else "ccu->device"
                            )
                            metrics["rssi"].add_metric(
                                labels=(base_labels + [direction]),
                                value=floatify(datapoint.value),
                            )
                        case DataPointType.ACTUAL_TEMPERATURE | DataPointType.TEMPERATURE:
                            metrics["temperature"].add_metric(
                                labels=base_labels, value=floatify(datapoint.value)
                            )
                        case DataPointType.HUMIDITY:
                            value = datapoint.value
                            match datapoint.valueunit:
                                case DataPointUnit.DECIMAL_PERCENT:
                                    value = floatify(value) / 100
                            metrics["humidity"].add_metric(
                                labels=base_labels, value=floatify(value)
                            )
                        case DataPointType.LEVEL:
                            match datapoint.valueunit:
                                case DataPointUnit.PERCENT:
                                    metrics["level"].add_metric(
                                        labels=base_labels,
                                        value=floatify(datapoint.value),
                                    )
                        case DataPointType.OPERATING_VOLTAGE:
                            match datapoint.valueunit:
                                case DataPointUnit.UNKNOWN:
                                    metrics["battery"].add_metric(
                                        labels=base_labels,
                                        value=floatify(datapoint.value),
                                    )
                                case DataPointUnit.VOLTAGE:
                                    ## I don't know why but only the socket powered devices seem to have the valueunit set.
                                    pass
                        case DataPointType.ENERGY_COUNTER:
                            value = datapoint.value
                            match datapoint.valueunit:
                                case DataPointUnit.WATT_HOUR:
                                    value = floatify(value) * 3600
                                case DataPointUnit.WATT:
                                    value = floatify(value) * 1
                            metrics["energy"].add_metric(
                                labels=base_labels, value=floatify(value)
                            )
                        case DataPointType.CURRENT:
                            value = datapoint.value
                            match datapoint.valueunit:
                                case DataPointUnit.MILLI_AMPERE:
                                    value = floatify(value) / 1000
                            metrics["current"].add_metric(
                                labels=base_labels, value=floatify(value)
                            )
                        case DataPointType.VOLTAGE:
                            match datapoint.valueunit:
                                case DataPointUnit.VOLTAGE:
                                    metrics["voltage"].add_metric(
                                        labels=base_labels,
                                        value=floatify(datapoint.value),
                                    )
                        case DataPointType.POWER:
                            match datapoint.valueunit:
                                case DataPointUnit.WATT:
                                    metrics["power"].add_metric(
                                        labels=base_labels,
                                        value=floatify(datapoint.value),
                                    )

        for metric in metrics.values():
            yield metric
        return super().collect()
