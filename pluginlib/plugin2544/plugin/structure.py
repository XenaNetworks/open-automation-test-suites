import asyncio
from decimal import Decimal
from typing import Dict, List, TYPE_CHECKING, Optional, Set, Tuple, Union
from dataclasses import dataclass, field
from pluginlib.plugin2544.conversion.model2544 import HeaderSegments
from pluginlib.plugin2544.model.m_protocol_segment import HeaderSegment
from pluginlib.plugin2544.model.m_test_config import (
    FrameSizeConfiguration,
    TestConfiguration,
)
from pluginlib.plugin2544.plugin.common import gen_macaddress
from pluginlib.plugin2544.plugin.data_model import (
    ArpRefreshData,
    RXTableData,
    StreamOffset,
)
from pluginlib.plugin2544.plugin.statistics import Statistic
from pluginlib.plugin2544.plugin.stream_struct import StreamStruct

from pluginlib.plugin2544.utils import exceptions, constants as const
from pluginlib.plugin2544.utils.logger import TestSuitPipe

from ..utils.field import MacAddress, IPv4Address, IPv6Address, NonNegativeDecimal

from xoa_core.core.test_suites.datasets import PortIdentity
from xoa_driver import enums, misc, utils, ports as xoa_ports, testers as xoa_testers

if TYPE_CHECKING:
    from ..model import (
        PortConfiguration,
        ThroughputTest,
        LatencyTest,
        FrameLossRateTest,
        BackToBackTest,
    )
    from xoa_driver.internals.core.commands import (
        P_TRAFFIC,
        P_RECEIVESYNC,
        P_CAPABILITIES,
    )


class BasePort:
    def __init__(
        self,
        tester: "xoa_testers.L23Tester",
        port: "xoa_ports.GenericL23Port",
        port_identity: PortIdentity,
        xoa_out: "TestSuitPipe",
    ):
        self._sync_status: bool = True
        self._traffic_status: bool = False
        self._tester = tester
        self._port = port
        self._xoa_out = xoa_out
        self.port_identity = port_identity

    @property
    def capabilities(self) -> "P_CAPABILITIES.GetDataAttr":
        return self._port.info.capabilities

    @property
    def port_statistic(self):
        return self._port.statistics

    @property
    def sync_status(self):
        return self._sync_status

    @property
    def traffic_status(self):
        return self._traffic_status

    async def _change_sync_status(
        self, port: "xoa_ports.GenericL23Port", get_attr: "P_RECEIVESYNC.GetDataAttr"
    ) -> None:
        before = self._sync_status
        after = self._sync_status = bool(get_attr.sync_status)
        # logger.warning(f"Change sync status from {before} to {after} ")
        if before and not after:
            raise exceptions.LossofPortSignal(port)

    async def _change_traffic_status(
        self, port: "xoa_ports.GenericL23Port", get_attr: "P_TRAFFIC.GetDataAttr"
    ) -> None:
        before = self._traffic_status
        after = self._traffic_status = bool(get_attr.on_off)

    async def __on_reservation_status(self, port: "xoa_ports.GenericL23Port", v):
        raise exceptions.LossofPortOwnership(self._port)

    async def __on_disconnect_tester(self, *args) -> None:
        raise exceptions.LossofTester(self._tester, self.port_identity.tester_id)

    async def set_toggle_port_sync(self, state: enums.OnOff) -> None:
        await self._port.tx_config.enable.set(state)

    def monitor_status(self) -> None:
        self._port.on_receive_sync_change(self._change_sync_status)

    def monitor_traffic(self) -> None:
        self._port.on_traffic_change(self._change_traffic_status)

    async def set_broadr_reach_mode(self, broadr_reach_mode: const.BRRModeStr) -> None:
        if self._port.is_brr_mode_supported == enums.YesNo.NO:
            self._xoa_out.send_warning(
                exceptions.BroadReachModeNotSupport(self.port_identity.name)
            )
        elif isinstance(self._port, const.BrrPorts):
            await self._port.brr_mode.set(broadr_reach_mode.to_xmp())

    async def set_mdi_mdix_mode(self, mdi_mdix_mode: const.MdiMdixMode) -> None:
        if self._port.info.capabilities.can_mdi_mdix == enums.YesNo.NO:
            self._xoa_out.send_warning(
                exceptions.MdiMdixModeNotSupport(self.port_identity.name)
            )
        elif isinstance(self._port, const.MdixPorts):
            await self._port.mdix_mode.set(mdi_mdix_mode.to_xmp())

    async def set_anlt(self) -> None:
        if not isinstance(self._port, const.PCSPMAPorts):
            return

        if bool(self._port.info.capabilities.can_auto_neg_base_r):
            await self._port.pcs_pma.auto_neg.settings.set(
                enums.AutoNegMode.ANEG_ON,
                enums.AutoNegTecAbility.DEFAULT_TECH_MODE,
                enums.AutoNegFECOption.NO_FEC,
                enums.AutoNegFECOption.NO_FEC,
                enums.PauseMode.NO_PAUSE,
            )
        else:
            self._xoa_out.send_warning(
                exceptions.ANLTNotSupport(self.port_identity.name)
            )
        if bool(self._port.info.capabilities.can_set_link_train):
            await self._port.pcs_pma.link_training.settings.set(
                enums.LinkTrainingMode.FORCE_ENABLE,
                enums.PAM4FrameSize.N16K_FRAME,
                enums.LinkTrainingInitCondition.NO_INIT,
                enums.NRZPreset.NRZ_NO_PRESET,
                enums.TimeoutMode.DEFAULT_TIMEOUT,
            )
        else:
            self._xoa_out.send_warning(
                exceptions.ANLTNotSupport(self.port_identity.name)
            )

    async def set_sweep_reduction(self, ppm: int) -> None:
        await self._port.speed.reduction.set(ppm=ppm)

    async def set_stagger_step(self, port_stagger_steps: int) -> None:
        if not port_stagger_steps:
            return
        await self._port.tx_config.delay.set(port_stagger_steps)  # P_TXDELAY

    async def set_auto_negotiation(self) -> None:

        if not bool(self._port.info.capabilities.can_set_autoneg) or not isinstance(
            self._port, const.AutoNegPorts
        ):
            self._xoa_out.send_warning(
                exceptions.AutoNegotiationNotSupport(self.port_identity.name)
            )
            return
        await self._port.autonneg_selection.set(enums.OnOff.ON)  # type:ignore

    async def set_fec_mode(self) -> None:
        # fec mode
        # TODO: need to distinguish which mode to set

        if self._port.info.capabilities.can_fec == enums.FECMode.OFF:
            self._xoa_out.send_warning(
                exceptions.FecModeNotSupport(self.port_identity.name)
            )
            return
        await self._port.fec_mode.set(enums.FECMode.ON)

    async def set_max_header(self, header_segments: List["HeaderSegment"]) -> None:
        # calculate max header length
        header_segments_val = sum(len(i.segment_value) for i in header_segments)
        for p in const.STANDARD_SEGMENT_VALUE:
            if header_segments_val <= p:
                header_segments_val = p
                break
        await self._port.max_header_length.set(header_segments_val)

    async def set_packet_size_if_mix(
        self, frame_sizes: "FrameSizeConfiguration"
    ) -> None:
        if not frame_sizes.packet_size_type.is_mix:
            return
        await self._port.mix.weights.set(*frame_sizes.mixed_sizes_weights)
        if frame_sizes.mixed_length_config:
            dic = frame_sizes.mixed_length_config.dict()
            for k, v in dic.items():
                position = int(k.split("_")[-1])
                await self._port.mix.lengths[position].set(v)

    @property
    async def mac_address(self) -> MacAddress:
        return MacAddress((await self._port.net_config.mac_address.get()).mac_address)

    async def send_packet(self, packet: str) -> None:
        await self._port.tx_single_pkt.send.set(packet)

    async def free(self) -> None:
        await self._port.reservation.set(enums.ReservedAction.RELEASE)

    async def reserve(self) -> None:
        if self._port.is_reserved_by_me():
            await self.free()
        elif self._port.is_reserved_by_others():
            await self._port.reservation.set(enums.ReservedAction.RELINQUISH)
        await utils.apply(
            self._port.reservation.set(enums.ReservedAction.RESERVE),
            self._port.reset.set(),
        )
        self._sync_status = await self.get_sync_status()
        self._traffic_status = await self.get_traffic_status()
        self._port.on_reservation_change(self.__on_reservation_status)
        self._tester.on_disconnected(self.__on_disconnect_tester)

    async def clear_statistic(self) -> None:
        await utils.apply(
            self._port.statistics.tx.clear.set(), self._port.statistics.rx.clear.set()
        )

    async def set_tx_time_limit(self, tx_timelimit: int) -> None:
        await self._port.tx_config.time_limit.set(int(tx_timelimit))

    async def set_gap_monitor(
        self, gap_monitor_start_microsec, gap_monitor_stop_frames
    ):
        await self._port.gap_monitor.set(
            gap_monitor_start_microsec, gap_monitor_stop_frames
        )

    async def set_traffic(self, traffic_state: enums.StartOrStop) -> None:
        await self._port.traffic.state.set(traffic_state)
        if not traffic_state:  # after stop traffic need to sleep 1 s
            await asyncio.sleep(1)

    async def set_arp_trucks(self, arp_datas: Set[RXTableData]) -> None:
        arp_chunk: List[misc.ArpChunk] = []
        for arp_data in arp_datas:
            arp_chunk.append(
                misc.ArpChunk(
                    *[
                        arp_data.destination_ip,
                        const.IPPrefixLength.IPv4.value,
                        enums.OnOff.OFF,
                        arp_data.dmac,
                    ]
                )
            )
        await self._port.arp_rx_table.set(arp_chunk)

    async def set_ndp_trucks(self, ndp_datas: Set[RXTableData]) -> None:
        ndp_chunk: List[misc.NdpChunk] = []
        for rx_data in ndp_datas:
            ndp_chunk.append(
                misc.NdpChunk(
                    *[
                        rx_data.destination_ip,
                        const.IPPrefixLength.IPv6.value,
                        enums.OnOff.OFF,
                        rx_data.dmac,
                    ]
                )
            )
        await self._port.ndp_rx_table.set(ndp_chunk)

    async def set_reply(self) -> None:
        await utils.apply(
            self._port.net_config.ipv4.arp_reply.set(enums.OnOff.ON),  # P_ARPREPLY
            self._port.net_config.ipv6.arp_reply.set(enums.OnOff.ON),  # P_ARPV6REPLY
            self._port.net_config.ipv4.ping_reply.set(enums.OnOff.ON),  # P_PINGREPLY
            self._port.net_config.ipv6.ping_reply.set(enums.OnOff.ON),  # P_PINGV6REPLY
        )

    async def set_tpld_mode(self, use_micro_tpld: bool) -> None:
        await self._port.tpld_mode.set(enums.TPLDMode(int(use_micro_tpld)))

    async def set_latency_offset(self, offset: int) -> None:
        await self._port.latency_config.offset.set(offset=offset)

    async def set_interframe_gap(self, interframe_gap: int) -> None:
        await self._port.interframe_gap.set(min_byte_count=interframe_gap)

    async def set_pause_mode(self, pause_mode_enabled: bool):
        await self._port.pause.set(on_off=enums.OnOff(int(pause_mode_enabled)))

    async def set_latency_mode(self, latency_mode: const.LatencyModeStr):
        await self._port.latency_config.mode.set(latency_mode.to_xmp())

    async def set_ipv4_address(self, ipv4_properties) -> None:
        subnet_mask = ipv4_properties.routing_prefix.to_ipv4()
        await self._port.net_config.ipv4.address.set(
            ipv4_address=ipv4_properties.address,
            subnet_mask=subnet_mask,
            gateway=ipv4_properties.gateway,
            wild="0.0.0.0",
        )

    async def set_ipv6_address(self, ipv6_properties) -> None:
        await self._port.net_config.ipv6.address.set(
            ipv6_address=ipv6_properties.address,
            gateway=ipv6_properties.gateway,
            subnet_prefix=ipv6_properties.routing_prefix,
            wildcard_prefix=128,
        )

    async def set_mac_address(self, mac_addr: str) -> None:
        await self._port.net_config.mac_address.set(mac_addr)

    @property
    def local_states(self):
        return self._port.local_states

    @property
    async def physics_speed(self) -> float:
        return (await self._port.speed.current.get()).port_speed * 1e6

    async def clear(self) -> None:
        await self.free()
        await self._tester.session.logoff()

    async def create_stream(self):
        return await self._port.streams.create()

    async def get_sync_status(self) -> bool:
        return bool((await self._port.sync_status.get()).sync_status)

    async def get_traffic_status(self) -> bool:
        return bool((await self._port.traffic.state.get()).on_off)


class PortStruct(BasePort):
    def __init__(
        self,
        tester: "xoa_testers.L23Tester",
        port: "xoa_ports.GenericL23Port",
        port_conf: "PortConfiguration",
        port_identity: PortIdentity,
        xoa_out: "TestSuitPipe",
    ) -> None:
        BasePort.__init__(self, tester, port, port_identity, xoa_out)
        self.port_conf = port_conf
        self.properties = Properties()
        self.stream_structs: List["StreamStruct"] = []
        self.rate: Decimal

    def init_counter(
        self, packet_size: Decimal, duration: Decimal, is_final: bool = False
    ):
        self.statistic = Statistic(
            frame_size=packet_size,
            duration=duration,
            is_final=is_final,
            interframe_gap=self.port_conf.inter_frame_gap,
        )

    @property
    def protocol_version(self) -> const.PortProtocolVersion:
        return self.port_conf.profile.protocol_version

    async def add_stream(
        self,
        rx_ports: List["PortStruct"],
        stream_id: int,
        tpldid: int,
        arp_mac: Optional[MacAddress] = None,
        stream_offset: Optional["StreamOffset"] = None,
    ):
        stream_struct = StreamStruct(
            self, rx_ports, stream_id, tpldid, arp_mac, stream_offset
        )
        self.stream_structs.append(stream_struct)

    async def configure_streams(self, test_conf: "TestConfiguration") -> None:
        for header_segment in self.port_conf.profile.header_segments:
            for field_value_range in header_segment.field_value_ranges:
                if field_value_range.reset_for_each_port:
                    field_value_range.reset()
        for stream_struct in self.stream_structs:
            await stream_struct.configure(test_conf)

    async def set_ip_address(self) -> None:
        if self.port_conf.profile.protocol_version.is_ipv4:
            # ip address, net mask, gateway
            await self.set_ipv4_address(self.port_conf.ipv4_properties)
        elif self.port_conf.profile.protocol_version.is_ipv6:
            await self.set_ipv6_address(self.port_conf.ipv6_properties)

    async def set_streams_packet_size(
        self, packet_size_type: enums.LengthType, min_size: int, max_size: int
    ):
        await asyncio.gather(
            *[
                stream_struct.set_packet_size(packet_size_type, min_size, max_size)
                for stream_struct in self.stream_structs
            ]
        )

    async def setup_port(
        self, test_conf: "TestConfiguration", latency_mode: const.LatencyModeStr
    ) -> None:
        if not test_conf.flow_creation_type.is_stream_based:
            await self.set_mac_address(
                str(
                    gen_macaddress(
                        test_conf.mac_base_address, self.properties.test_port_index
                    )
                )
            )
        mode = self.port_conf.port_speed_mode.to_xmp()
        if mode not in self.local_states.port_possible_speed_modes:
            self._xoa_out.send_warning(exceptions.PortSpeedWarning(mode))
        await self.set_latency_offset(self.port_conf.latency_offset_ms)
        await self.set_interframe_gap(self.port_conf.inter_frame_gap)
        await self.set_pause_mode(self.port_conf.pause_mode_enabled)
        await self.set_latency_mode(latency_mode)
        # self.port.speed.mode.selection.set(mode),
        await self.set_tpld_mode(test_conf.use_micro_tpld_on_demand)
        await self.set_reply()
        await self.set_ip_address()
        await self.set_broadr_reach_mode(self.port_conf.broadr_reach_mode)
        await self.set_mdi_mdix_mode(self.port_conf.mdi_mdix_mode)
        if self.port_conf.fec_mode:
            await self.set_fec_mode()
        if self.port_conf.anlt_enabled:
            await self.set_anlt()
        if not self.port_conf.auto_neg_enabled:
            await self.set_auto_negotiation()
        await self.set_max_header(self.port_conf.profile.header_segments)
        await self.set_sweep_reduction(self.port_conf.speed_reduction_ppm)
        await self.set_stagger_step(test_conf.port_stagger_steps)
        await self.set_packet_size_if_mix(test_conf.frame_sizes)

    async def set_rx_tables(self):
        await self.set_arp_trucks(self.properties.arp_trunks)
        await self.set_ndp_trucks(self.properties.ndp_trunks)

    @property
    async def port_speed(self) -> Decimal:
        port_speed = await self.physics_speed
        if self.port_conf.port_rate_cap_profile.is_custom:
            port_speed = min(self.port_conf.port_rate, port_speed)
        return Decimal(str(port_speed))

    async def get_use_port_speed(self) -> NonNegativeDecimal:
        tx_speed = await self.port_speed
        if self.port_conf.peer_config_slot and len(self.properties.peers) == 1:
            peer_struct = self.properties.peers[0]
            rx_speed = await peer_struct.port_speed
            tx_speed = min(tx_speed, rx_speed)
        tx_speed = (
            tx_speed
            * Decimal(str(1e6 - self.port_conf.speed_reduction_ppm))
            / Decimal(str(1e6))
        )
        return NonNegativeDecimal(str(tx_speed))


TypeConf = Union["ThroughputTest", "LatencyTest", "FrameLossRateTest", "BackToBackTest"]


@dataclass
class Properties:
    num_modifiersL2: int = 1
    dest_port_count: int = 0
    test_port_index: int = 0
    high_dest_port_count: int = 0
    low_dest_port_count: int = 0
    lowest_dest_port_index: int = -1
    highest_dest_port_index: int = -1
    address_refresh_data_set: Set[ArpRefreshData] = field(default_factory=set)
    peers: List["PortStruct"] = field(default_factory=list)
    arp_trunks: Set[RXTableData] = field(default_factory=set)
    ndp_trunks: Set[RXTableData] = field(default_factory=set)

    def get_modifier_range(self, stream_id: int) -> Tuple[int, int]:
        if stream_id == 0:
            if self.num_modifiersL2 == 2:
                modifier_range = (
                    self.lowest_dest_port_index,
                    self.test_port_index - 1,
                )
            elif self.dest_port_count > 0:
                modifier_range = (
                    self.lowest_dest_port_index,
                    self.highest_dest_port_index,
                )
            else:
                modifier_range = (
                    self.test_port_index,
                    self.test_port_index,
                )
        else:
            modifier_range = (
                self.test_port_index + 1,
                self.highest_dest_port_index,
            )

        return modifier_range

    def register_peer(self, peer: "PortStruct") -> None:
        if peer not in self.peers:
            self.peers.append(peer)
        if peer.properties.test_port_index == self.test_port_index:
            return
        self.dest_port_count += 1
        if peer.properties.test_port_index < self.test_port_index:
            self.low_dest_port_count += 1
        elif peer.properties.test_port_index > self.test_port_index:
            self.high_dest_port_count += 1
        self.num_modifiersL2 = (
            2 if (self.low_dest_port_count > 0 and self.high_dest_port_count > 0) else 1
        )
        self.lowest_dest_port_index = (
            peer.properties.test_port_index
            if self.lowest_dest_port_index == -1
            else min(self.lowest_dest_port_index, peer.properties.test_port_index)
        )
        self.highest_dest_port_index = (
            peer.properties.test_port_index
            if self.highest_dest_port_index == -1
            else max(self.highest_dest_port_index, peer.properties.test_port_index)
        )
