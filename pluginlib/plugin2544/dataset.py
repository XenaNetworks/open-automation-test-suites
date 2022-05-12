from decimal import getcontext
from typing import Dict, Tuple
from pydantic import (
    BaseModel,
    validator,
)


from .model.m_test_config import TestConfiguration
from .model.m_port_config import PortConfiguration
from .model.m_protocol_segment import ProtocolSegmentProfileConfig
from .model.m_test_type_config import TestTypesConfiguration
from .utils.constants import (
    RateResultScopeType,
    PortGroup,
    TestTopology,
    TrafficDirection,
)
from .utils import exceptions

getcontext().prec = 6

ProtoSegType = Dict[str, "ProtocolSegmentProfileConfig"]
PortConfType = Dict[str, "PortConfiguration"]


class PluginModel2544(BaseModel):  # Main Model
    test_configuration: TestConfiguration
    protocol_segments: ProtoSegType
    ports_configuration: PortConfType
    test_types_configuration: TestTypesConfiguration

    # Computed Properties
    in_same_ipnetwork: bool = False
    with_same_gateway: bool = False
    has_l3: bool = False

    @validator("ports_configuration", always=True)
    def set_ports_rx_tx_type(
        cls, port_configs: "PortConfType", values
    ) -> "PortConfType":
        if "test_configuration" in values:
            direction = values["test_configuration"].direction
            for config_index, port in port_configs.items():
                if not port.port_config_slot:
                    port.port_config_slot = config_index
                if port.port_config_slot == port.peer_config_slot:
                    pass
                elif direction == TrafficDirection.EAST_TO_WEST:
                    if port.port_group.is_east:
                        port.is_rx_port = False
                    elif port.port_group.is_west:
                        port.is_tx_port = False
                elif direction == TrafficDirection.WEST_TO_EAST:
                    if port.port_group.is_east:
                        port.is_tx_port = False
                    elif port.port_group.is_west:
                        port.is_rx_port = False
        return port_configs

    @validator("ports_configuration", always=True)
    def set_ip_properties(cls, v: "PortConfType", values) -> "PortConfType":
        if "protocol_segments" in values:
            for _, port_config in v.items():
                profile_id = port_config.profile_id
                port_config.profile = values["protocol_segments"][profile_id]
                if port_config.profile.protocol_version.is_ipv4:
                    port_config.ip_properties = port_config.ipv4_properties
                elif port_config.profile.protocol_version.is_ipv6:
                    port_config.ip_properties = port_config.ipv6_properties
                if (
                    port_config.profile.protocol_version.is_l3
                    and port_config.ip_properties.address.is_empty
                ):
                    raise exceptions.IPAddressMissing()
        return v

    @validator("ports_configuration", always=True)
    def check_port_count(cls, v: "PortConfType", values) -> "PortConfType":
        require_ports = 2
        if "test_configuration" in values:
            topology: TestTopology = values["test_configuration"].topology
            if topology.is_pair_topology:
                require_ports = 1
            if len(v) < require_ports:
                raise exceptions.PortConfigNotEnough(require_ports)
        return v

    @validator("ports_configuration", always=True)
    def check_port_groups_and_peers(cls, v: "PortConfType", values) -> "PortConfType":
        if "test_configuration" in values:
            topology: TestTopology = values["test_configuration"].topology
            ports_in_east = 0
            ports_in_west = 0
            uses_port_peer = topology.is_pair_topology
            for _, port_config in v.items():
                if not topology.is_mesh_topology:
                    ports_in_east, ports_in_west = cls.count_port_group(
                        port_config, uses_port_peer, ports_in_east, ports_in_west
                    )
                if uses_port_peer:
                    cls.check_port_peer(port_config, v)
            if not topology.is_mesh_topology:
                for i, group in (ports_in_east, "East"), (ports_in_west, "West"):
                    if not i:
                        raise exceptions.PortGroupError(group)
        return v

    @validator("ports_configuration", always=True)
    def check_modifier_mode_and_segments(
        cls, v: "PortConfType", values
    ) -> "PortConfType":
        if "test_configuration" in values:
            flow_creation_type = values["test_configuration"].flow_creation_type
            for _, port_config in v.items():
                if (
                    not flow_creation_type.is_stream_based
                ) and port_config.profile.protocol_version.is_l3:
                    raise exceptions.ModifierBasedNotSupportL3()
        return v

    @validator("test_types_configuration", always=True)
    def check_test_type_enable(
        cls, v: "TestTypesConfiguration"
    ) -> "TestTypesConfiguration":
        if not any(
            {
                v.throughput_test.enabled,
                v.latency_test.enabled,
                v.frame_loss_rate_test.enabled,
                v.back_to_back_test.enabled,
            }
        ):
            raise exceptions.TestTypesError()
        return v

    @validator("test_types_configuration", always=True)
    def check_result_scope(cls, v: "TestTypesConfiguration", values):
        if not "test_configuration" in values:
            return v
        if (
            v.throughput_test.enabled
            and v.throughput_test.rate_iteration_options.result_scope
            == RateResultScopeType.PER_SOURCE_PORT
            and not values["test_configuration"].flow_creation_type.is_stream_based
        ):
            raise exceptions.ModifierBasedNotSupportPerPortResult()
        return v

    @staticmethod
    def count_port_group(
        port_config: "PortConfiguration",
        uses_port_peer: bool,
        ports_in_east: int,
        ports_in_west: int,
    ) -> Tuple[int, int]:
        is_looped = port_config.port_config_slot == port_config.peer_config_slot
        if port_config.port_group.is_east:
            ports_in_east += 1
            if uses_port_peer and is_looped:
                ports_in_west += 1

        elif port_config.port_group.is_west:
            ports_in_west += 1
            if uses_port_peer and is_looped:
                ports_in_east += 1

        return ports_in_east, ports_in_west

    @staticmethod
    def check_port_peer(
        port_config: "PortConfiguration",
        ports_configuration: Dict[str, "PortConfiguration"],
    ):
        peer_config_slot = port_config.peer_config_slot
        if not peer_config_slot:
            raise exceptions.PortPeerNeeded()
        if (
            peer_config_slot not in ports_configuration
            or ports_configuration[peer_config_slot].peer_config_slot
            != port_config.port_config_slot
        ):
            raise exceptions.PortPeerInconsistent()

    @validator("in_same_ipnetwork", always=True)
    def set_in_same_ipnetwork(cls, v, values):
        if "ports_configuration" in values:
            conf = values["ports_configuration"]
            networks = set(
                [
                    p.ip_properties.address.network(p.ip_properties.routing_prefix)
                    for p in conf.values()
                ]
            )

            v = len(networks) == 1
        return v

    @validator("with_same_gateway", always=True)
    def set_with_same_gateway(cls, v: bool, values) -> bool:
        if "ports_configuration" in values:
            confs = values["ports_configuration"]
            gateways = set([p.ip_properties.gateway for p in confs.values()])
            v = len(gateways) == 1
        return v

    @validator("has_l3", always=True)
    def set_has_l3(cls, v: bool, values) -> bool:
        if "ports_configuration" in values:
            confs = values["ports_configuration"]
            return any([conf.profile.protocol_version.is_l3 for conf in confs.values()])
        return False

    @validator("ports_configuration", always=True)
    def check_port_group(cls, v, values):
        if "ports_configuration" in values and "test_configuration" in values:
            for k, p in values["ports_configuration"].items():
                if (
                    p.port_group == PortGroup.UNDEFINED
                    and not values["test_configuration"].topology.is_mesh_topology
                ):
                    raise exceptions.PortGroupNeeded()
        return v
