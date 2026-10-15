import pytest

from canon_eos_utility import discovery

pytestmark = pytest.mark.skipif(not discovery.ZEROCONF_AVAILABLE, reason="zeroconf not installed")


class _FakeInfo:
    def __init__(self, addresses, port=15740, properties=None):
        self._addresses = addresses
        self.port = port
        self.properties = properties or {}

    def parsed_addresses(self):
        return list(self._addresses)


class _FakeZeroconf:
    def __init__(self, info):
        self._info = info

    def get_service_info(self, type_, name, timeout=0):
        return self._info


def test_instance_name():
    assert (
        discovery.instance_name("ICPO-WFTEOSSystemService859408._ptp._tcp.local.")
        == "ICPO-WFTEOSSystemService859408"
    )


def test_listener_maps_service_to_ipv4_camera():
    info = _FakeInfo(["fe80::1", "192.168.0.100"])
    found = []
    lost = []
    listener = discovery._PtpServiceListener(found.append, lost.append)

    listener.add_service(
        _FakeZeroconf(info),
        discovery.PTP_SERVICE_TYPE,
        "ICPO-WFTEOSSystemService859408._ptp._tcp.local.",
    )

    assert len(found) == 1
    camera = found[0]
    assert camera.address == "192.168.0.100"  # prefers IPv4
    assert camera.port == 15740
    assert "859408" in camera.guid

    listener.remove_service(
        _FakeZeroconf(info),
        discovery.PTP_SERVICE_TYPE,
        "ICPO-WFTEOSSystemService859408._ptp._tcp.local.",
    )
    assert lost == ["ICPO-WFTEOSSystemService859408"]


def test_listener_uses_txt_model_when_present():
    info = _FakeInfo(["192.168.0.100"], properties={b"ty": b"Canon EOS R5"})
    found = []
    listener = discovery._PtpServiceListener(found.append, None)
    listener.add_service(
        _FakeZeroconf(info),
        discovery.PTP_SERVICE_TYPE,
        "ICPO-WFTEOSSystemService859408._ptp._tcp.local.",
    )
    assert found[0].display_name == "Canon EOS R5"


def test_listener_ignores_unresolvable_service():
    found = []
    listener = discovery._PtpServiceListener(found.append, None)
    listener.add_service(None, discovery.PTP_SERVICE_TYPE, "x._ptp._tcp.local.")
    assert found == []
