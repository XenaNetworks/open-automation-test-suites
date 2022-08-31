import re
from enum import Enum
from random import randint
from loguru import logger
from typing import Any, Callable, Dict, Generator, List, Optional, Protocol, Union
from xoa_driver.enums import ProtocolOption
# from ..common import copy_to, is_byte_values_zero
# from pluginlib.plugin2544.plugin.data_model import AddressCollection
# from pluginlib.plugin2544.utils import constants
# from pluginlib.plugin2544.utils.constants import SegmentType
from pydantic import BaseModel
from pydantic.class_validators import validator
from pydantic.fields import Field


HexString = str


class BinaryString(str):
    def __new__(cls, content) -> "BinaryString":
        if not re.search("^[01]+$", content):
            raise ValueError('binary string must zero or one')
        return str.__new__(cls, content)

    @property
    def is_all_zero(self) -> bool:
        return bool(re.search("^[0]+$", self))

class ModifierActionOption(Enum):
    INC = "increment"
    DEC = "decrement"
    RANDOM = "random"


class PortProtocolVersion(Enum):
    ETHERNET = 0
    IPV4 = 4
    IPV6 = 6

    @property
    def is_ipv4(self) -> bool:
        return self == type(self).IPV4

    @property
    def is_ipv6(self) -> bool:
        return self == type(self).IPV6

    @property
    def is_l3(self) -> bool:
        return self != type(self).ETHERNET


def bitstring_to_bytes(s) -> bytes:
    return int(s, 2).to_bytes((len(s) + 7) // 8, byteorder='big')

def wrap_add_16(data: bytearray, offset_num: int) -> bytearray:
    # Needs validation
    checksum = 0
    data[offset_num + 0] = 0
    data[offset_num + 1] = 0
    for i in range(0, len(data), 2):
        w = (data[i + 0] << 8) + data[i + 1]
        checksum += w
        if checksum > 0xFFFF:
            checksum = (1 + checksum) & 0xFFFF  # add carry back in as lsb
    data[offset_num + 0] = 0xFF + 1 + (~(checksum >> 8))
    data[offset_num + 1] = 0xFF + 1 + (~(checksum & 0xFF))
    return data

def hex_to_bitstring(hex_vlaue: int) -> BinaryString:
    return BinaryString(f'{hex_vlaue:0>42b}')

def hex_string_to_binary_string(hex_vlaue: str) -> BinaryString:
    return BinaryString(f'{int(hex_vlaue):0>42b}')




class EnumActions(Enum):
    INCR = "increment"
    DECR = "decrement"
    RAND = "random"

class SegmentType(Enum):
    # RAW = "raw"
    ETHERNET = "ethernet"
    VLAN = "vlan"
    ARP = "arp"
    IP = "ipv4"
    IPV6 = "ipv6"
    UDP = "udp"
    TCP = "tcp"
    LLC = "llc"
    SNAP = "snap"
    GTP = "gtp"
    ICMP = "icmp"
    # ICMPV6 = "icmpv6"
    RTP = "rtp"
    RTCP = "rtcp"
    STP = "stp"
    SCTP = "sctp"  # added
    MACCTRL = "macctrl"
    MPLS = "mpls"
    PBBTAG = "pbbtag"
    FCOE = "fcoe"  # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!1
    FC = "fc"
    # FCOEHEAD = "fcoehead"  # added
    FCOETAIL = "fcoetail"
    IGMPV3L0 = "igmpv3l0"
    IGMPV3L1 = "igmpv3l1"
    # IGMPV3GR = "igmpv3gr"
    # IGMPV3MR = "igmpv3mr"
    # MLDV2AR = "mldv2ar"
    UDPCHECK = "udpcheck"
    IGMPV2 = "igmpv2"
    # "MPLS_TP_OAM"
    GRE_NOCHECK = "gre_nocheck"
    GRE_CHECK = "gre_check"
    TCPCHECK = "tcp_check"
    # "GTPV1L0"
    # "GTPV1L1"
    # "GTPV2L0"
    # "GTPV2L1"
    IGMPV1 = "igmpv1"
    # "PWETHCTRL"
    VXLAN = "vxlan"
    # "ETHERNET_8023"
    NVGRE = "nvgre"
    # "DHCPV4"
    # "GENEVE"
    # "XENA_TPLD"
    # "XENA_TPLD_PI"
    # "XENA_MICROTPLD"
    # "ETHERNET_FCS"
    # "MACCTRLPFC"
    # "ECPRI"
    # "ROE"
    # "ETHERTYPE"
    # Generat RAW form 1...64 bytes
    _ignore_ = "SegmentType i"
    SegmentType = vars()
    for i in range(1, 65):
        SegmentType[f"RAW_{i}"] = f"raw_{i}"  # type: ignore

    @property
    def is_raw(self) -> bool:
        return self.value.lower().startswith("raw")

    @property
    def raw_length(self) -> int:
        if not self.is_raw:
            return 0
        return int(self.value.split("_")[-1])

    def to_xmp(self) -> "ProtocolOption":
        return ProtocolOption[self.name]

    @property
    def is_ethernet(self) -> bool:
        return self == SegmentType.ETHERNET

    @property
    def is_ipv4(self) -> bool:
        return self == SegmentType.IP

    @property
    def is_ipv6(self) -> bool:
        return self == SegmentType.IPV6


class ValueRange(BaseModel):
    start_value: int
    step_value: int
    stop_value: int
    action: EnumActions
    restart_for_each_port: bool
    current_count: int = 0 #

    def reset(self) -> None:
        self.current_count = 0

    def get_current_value(self) -> int:
        if self.action == ModifierActionOption.INC:
            current_value = self.start_value + self.current_count * self.step_value
            if current_value > self.stop_value:
                current_value = self.start_value
                self.reset()
        elif self.action == ModifierActionOption.DEC:
            current_value = self.start_value - self.current_count * self.step_value
            if current_value < self.stop_value:
                current_value = self.start_value
                self.reset()
        else:
            boundary = [self.start_value, self.stop_value]
            current_value = randint(min(boundary), max(boundary))
        self.current_count += 1
        return current_value


class HWModifier(BaseModel):
    start_value: int
    step_value: int
    stop_value: int
    repeat: int
    action: EnumActions
    position: int
    mask: HexString


class SegmentField(BaseModel):
    name: str
    value: BinaryString
    bit_length: int
    bit_segment_position: int = 0 # the bit position from the start of the segment
    hw_modifier: Optional[HWModifier]
    value_range: Optional[ValueRange]

    class Config:
        validate_assignment = True

    def __init__(self, **data: Any):
        super().__init__(**data)
        self.value = BinaryString(self.value)

    @property
    def is_ipv4_address(self) -> bool:
        return self.name in ("Src IP Addr", "Dest IP Addr") # field name change to src/dest ipv4 addr?

    def apply_value_range_if_exists(self) -> Union[BinaryString, str]:
        if not self.value_range:
            return self.value

        value_range_str = bin( self.value_range.get_current_value() )[2:].zfill(self.bit_length)
        result = (
            self.value[:self.bit_segment_position]
            + value_range_str
            + self.value[self.bit_segment_position + self.bit_length]
        )
        return result

    def prepare(self) -> Union[BinaryString, str]:
        return self.apply_value_range_if_exists()

    def set_field_value(self, new_value: BinaryString) -> None:
        if len(new_value) == self.bit_length:
            self.value = new_value
        else:
            raise ValueError(f'value length {len(new_value)} not match {self.bit_length}({self.name})')

    @property
    def is_value_all_zero(self) -> bool:
        return self.value.is_all_zero



class Segment(BaseModel):
    segment_type: SegmentType
    fields: list[SegmentField]
    checksum_offset: Optional[int] = None

    # compute value after init, maybe is wrong approche, need discuss
    is_field_src_value_all_zero: Optional[bool] = False
    is_field_dst_value_all_zero: Optional[bool] = False

    def saving_is_original_value_zero(self) -> None:
        if self.segment_type.is_ethernet:
            self.is_field_src_value_all_zero = self['Src MAC addr'].is_value_all_zero
            self.is_field_dst_value_all_zero = self['Dst MAC addr'].is_value_all_zero
        elif self.segment_type.is_ipv4:
            self.is_field_src_value_all_zero = self['Src IP Addr'].is_value_all_zero
            self.is_field_dst_value_all_zero = self['Dest IP Addr'].is_value_all_zero
        elif self.segment_type.is_ipv6:
            self.is_field_src_value_all_zero = self['Src IPv6 Addr'].is_value_all_zero
            self.is_field_dst_value_all_zero = self['Dest IPv6 Addr'].is_value_all_zero

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data: Any):
        super().__init__(**data)
        self.saving_is_original_value_zero()

    @property
    def hw_modifiers(self) -> Generator[HWModifier, None, None]:
        return (f.hw_modifier for f in self.fields if f.hw_modifier)

    @property
    def value_ranges(self) -> Generator[ValueRange, None, None]:
        return (f.value_range for f in self.fields if f.value_range)

    @validator('checksum_offset')
    def is_digit(cls, value):
        if value and not isinstance(value, int):
            raise ValueError('checksum offset must digit')
        return value

    def prepare(self) -> bytearray:
        result = bytearray(bitstring_to_bytes(''.join(f.prepare() for f in self.fields)))

        if self.checksum_offset:
            result = wrap_add_16(result, self.checksum_offset)

        return result

    def __getitem__(self, field_name: str) -> SegmentField:
        for field in self.fields:
            if field.name == field_name:
                return field
        raise KeyError(field_name)

    def __setitem__(self, field_name: str, new_value: BinaryString) -> None:
        self[field_name].set_field_value(new_value)

    def __len__(self) -> int:
        """segment length in bit"""
        return sum(f.bit_length for f in self.fields)

    @property
    def modifier_count(self) -> int:
        return sum(1 for f in self.fields if f.hw_modifier)

    # should make it as validator
    # def setup_fields(self, current_segment_bit_offset: int) -> None:
    #     for field in self.fields:
    #         if field.value_range:
    #             max_val = max(field.value_range.start_value, field.value_range.stop_value)
    #             theory_max = pow(2, field.bit_length)
    #             if max_val >= theory_max: # why not fvr.stop_value >= can_max?
    #                 raise Exception('over max', field.name, theory_max)

class ProtocolSegmentProfileConfig(BaseModel):
    header_segments: list[Segment] = []

    def __getitem__(self, segment_type: SegmentType) -> List[Segment]:
        return [segment for segment in self.header_segments if segment.segment_type == segment_type]

    def prepare(self) -> bytearray:
        result = bytearray()
        for s in self.header_segments:
            result += s.prepare()
        return result

    def get_segment(self, segment_type: SegmentType, index: int = 0) -> Segment:
        return self[segment_type][index]

    @property
    def protocol_version(self) -> PortProtocolVersion:
        v = PortProtocolVersion.ETHERNET
        for i in self.header_segments:
            if i.segment_type == SegmentType.IPV6:
                v = PortProtocolVersion.IPV6
                break
            elif i.segment_type == SegmentType.IP:
                v = PortProtocolVersion.IPV4
                break
        return v

    @property
    def segment_id_list(self) -> List[ProtocolOption]:
        return [h.segment_type.to_xmp() for h in self.header_segments]

    def __len__(self) -> int:
        """header length in bit"""
        return sum(len(hs) for hs in self.header_segments)

    @property
    def packet_header_length(self) -> int:
        """header length in byte for convenient use with xoa-driver"""
        return len(self) // 8

    @property
    def modifier_count(self) -> int:
        return sum(hs.modifier_count for hs in self.header_segments)

fake_data = {
    'header_segments': [
        {
            'segment_type': 'ethernet',
            'fields': [
                {
                    'name': 'dst mac address',
                    'bit_length': 48,
                    'bit_segment_position': 0,
                    'value': '100101101100101111011110010110001001101000000111',
                    'value_range': {'start_value': 0, 'stop_value': 255, 'step_value': 1, 'action': 'increment', 'restart_for_each_port': False},
                    'modifier': {'offset': 2, 'start_value': 0, 'stop_value': 10, 'step_value': 1, 'repeat': 1, 'action': 'increment', 'mask': '//8='},
                },
                {'name': 'src mac address', 'bit_length': '48', 'value': '110100101111000111000110101011010111101000100101', 'bit_segment_position': 49},
                {'name': 'ether type', 'bit_length': '16', 'value': '1111111111111111', 'bit_segment_position': 96},
            ],
        }
    ],
}

def setup_segment_ethernet(segment: Segment, src_mac: BinaryString, dst_mac: BinaryString, arp_mac: Optional[BinaryString] = None):
    dst_mac = (dst_mac if not arp_mac or arp_mac.is_all_zero else arp_mac)
    if not dst_mac.is_all_zero and segment.is_field_dst_value_all_zero:
        segment['Dst MAC addr'].value = dst_mac
    if not src_mac.is_all_zero and segment.is_field_src_value_all_zero:
        segment['Src MAC addr'].value = src_mac

def setup_segment_ipv4(segment: Segment, src_ipv4: BinaryString, dst_ipv4: BinaryString):
    if segment.is_field_src_value_all_zero:
        segment['Src IP addr'] = src_ipv4
    if segment.is_field_dst_value_all_zero:
        segment['Dst IP addr'] = dst_ipv4

def setup_segment_ipv6(segment: Segment, src_ipv6: BinaryString, dst_ipv6: BinaryString):
    if segment.is_field_src_value_all_zero:
        segment['Src IPv6 addr'] = src_ipv6
    if segment.is_field_dst_value_all_zero:
        segment['Dst IPv6 addr'] = dst_ipv6

# hsp = HeaderSegmentsProfileBase.parse_obj(fake_data)

# segment = hsp[SegmentType.ETHERNET][0]

# segment['dst mac address'] = hex_to_bitstring(0xbc6348b035e7)