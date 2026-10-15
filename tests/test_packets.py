from canon_eos_utility.constants import PacketType
from canon_eos_utility.protocol.packets import (
    DataPacket,
    EndData,
    InitCommandAck,
    InitCommandRequest,
    InitEventAck,
    InitEventRequest,
    OperationRequest,
    OperationResponse,
    StartData,
    encode_packet,
    parse_payload,
    read_frame,
)


def _roundtrip(packet):
    encoded = encode_packet(packet)
    frame = read_frame(encoded)
    assert frame is not None
    payload, consumed = frame
    assert consumed == len(encoded)
    return parse_payload(payload)


def test_init_command_request_roundtrip():
    guid = bytes(range(16))
    packet = InitCommandRequest(guid=guid, name="EOS Utility", version=1)
    decoded = _roundtrip(packet)
    assert isinstance(decoded, InitCommandRequest)
    assert decoded.guid == guid
    assert decoded.name == "EOS Utility"
    assert decoded.version == 1


def test_init_command_request_wire_length_matches_article():
    # 8 (len+type) + 16 (guid) + 14 ("iPhone" utf16 + nul) + 4 (version) == 42
    packet = InitCommandRequest(guid=bytes(16), name="iPhone")
    encoded = encode_packet(packet)
    assert len(encoded) == 42


def test_init_command_ack_roundtrip():
    decoded = _roundtrip(InitCommandAck(connection_number=1, guid=bytes(16), name="70D"))
    assert isinstance(decoded, InitCommandAck)
    assert decoded.connection_number == 1
    assert decoded.name == "70D"
    assert decoded.version == "1.0"


def test_init_event_roundtrip():
    decoded = _roundtrip(InitEventRequest(connection_number=7))
    assert isinstance(decoded, InitEventRequest)
    assert decoded.connection_number == 7
    assert isinstance(_roundtrip(InitEventAck()), InitEventAck)


def test_operation_request_roundtrip():
    packet = OperationRequest(data_phase=1, operation_code=0x1002, transaction_id=3, params=[1])
    decoded = _roundtrip(packet)
    assert isinstance(decoded, OperationRequest)
    assert decoded.operation_code == 0x1002
    assert decoded.params == [1]


def test_operation_response_roundtrip():
    decoded = _roundtrip(OperationResponse(response_code=0x2001, transaction_id=5))
    assert isinstance(decoded, OperationResponse)
    assert decoded.response_code == 0x2001


def test_data_packets_roundtrip():
    assert _roundtrip(StartData(transaction_id=1, total_length=1234)).total_length == 1234
    assert _roundtrip(DataPacket(transaction_id=1, data=b"abc")).data == b"abc"
    assert _roundtrip(EndData(transaction_id=1, data=b"xyz")).data == b"xyz"


def test_read_frame_partial_returns_none():
    encoded = encode_packet(InitEventAck())
    assert read_frame(encoded[:2]) is None
    assert read_frame(encoded[: len(encoded) - 1]) is None
    frame = read_frame(encoded)
    assert frame is not None


def test_packet_type_constant():
    assert int(PacketType.INIT_COMMAND_REQUEST) == 1
    assert int(PacketType.OPERATION_RESPONSE) == 7
