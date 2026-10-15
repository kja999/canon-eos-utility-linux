"""Camera discovery.

Canon EOS cameras advertise themselves in two ways:

* **mDNS / DNS-SD** — a ``_ptp._tcp.local`` service instance such as
  ``ICPO-WFTEOSSystemService859408`` (this is what ``avahi-browse _ptp._tcp``
  shows).  We browse for it continuously and can auto-connect on sight.
* **UPnP/SSDP** — the ``urn:schemas-canon-com:service:ICPO-WFTEOSSystemService:1``
  service type, which we probe with an ``M-SEARCH`` request.

mDNS browsing uses the pure-Python :mod:`zeroconf` package when available; if it
is not installed the SSDP probe and manual host entry still work.
"""

from __future__ import annotations

import socket
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .constants import CANON_SERVICE_TYPE, PTPIP_PORT, SSDP_MULTICAST_ADDR, SSDP_PORT

#: Canon's PTP-over-IP DNS-SD service type.
PTP_SERVICE_TYPE = "_ptp._tcp.local."

try:  # pragma: no cover - exercised implicitly
    from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

    ZEROCONF_AVAILABLE = True
except ImportError:  # pragma: no cover
    ServiceBrowser = ServiceListener = ServiceInfo = Zeroconf = None  # type: ignore[assignment]
    ZEROCONF_AVAILABLE = False

_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_MULTICAST_ADDR}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    f"ST: {CANON_SERVICE_TYPE}\r\n"
    "\r\n"
)


@dataclass
class DiscoveredCamera:
    address: str
    guid: str = ""
    model: str = ""
    location: str = ""
    port: int = PTPIP_PORT

    @property
    def display_name(self) -> str:
        return self.model or self.address


def _parse_headers(payload: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in payload.splitlines()[1:]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    return headers


def _address_from_location(location: str, fallback: str) -> str:
    if not location:
        return fallback
    # http://<host>:<port>/upnp/...
    without_scheme = location.split("://", 1)[-1]
    host_port = without_scheme.split("/", 1)[0]
    host = host_port.split(":", 1)[0]
    return host or fallback


def fetch_device_description(location: str, timeout: float = 2.0) -> tuple[str, str]:
    """Return ``(model_name, unique_device_name)`` from a UPnP description URL."""
    try:
        with urllib.request.urlopen(location, timeout=timeout) as response:  # noqa: S310
            data = response.read()
    except Exception:  # pragma: no cover - network dependent
        return "", ""

    try:
        root = ET.fromstring(data)
    except ET.ParseError:  # pragma: no cover
        return "", ""

    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    model = root.findtext(".//d:modelName", default="", namespaces=ns)
    model_description = root.findtext(".//d:modelDescription", default="", namespaces=ns)
    udn = root.findtext(".//d:UDN", default="", namespaces=ns)
    return (model or model_description), udn


def discover(timeout: float = 3.0) -> list[DiscoveredCamera]:
    """Block until ``timeout`` elapses and return the cameras found."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    sock.bind(("", 0))

    found: dict[str, DiscoveredCamera] = {}
    try:
        sock.sendto(_MSEARCH.encode("ascii"), (SSDP_MULTICAST_ADDR, SSDP_PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:  # pragma: no cover
                break
            headers = _parse_headers(data.decode("utf-8", "replace"))
            st = headers.get("st", "")
            usn = headers.get("usn", "")
            if CANON_SERVICE_TYPE not in st and CANON_SERVICE_TYPE not in usn:
                continue
            location = headers.get("location", "")
            address = _address_from_location(location, addr[0])
            if any(cam.address == address for cam in found.values()):
                continue
            model, udn = fetch_device_description(location) if location else ("", "")
            guid = usn.split("::", 1)[0] or udn
            found[address] = DiscoveredCamera(
                address=address,
                guid=guid,
                model=model,
                location=location,
            )
    finally:
        sock.close()

    return list(found.values())


def probe_host(host: str, port: int = PTPIP_PORT, timeout: float = 1.5) -> bool:
    """Return ``True`` if a PTP/IP service accepts TCP connections on ``host``."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# mDNS / DNS-SD browsing (passive watching)
# ---------------------------------------------------------------------------


def instance_name(service_name: str) -> str:
    """``ICPO-...859408._ptp._tcp.local.`` -> ``ICPO-...859408``."""
    return service_name.split("._", 1)[0]


if ZEROCONF_AVAILABLE:

    class _PtpServiceListener(ServiceListener):
        """Resolves ``_ptp._tcp`` service instances into :class:`DiscoveredCamera`."""

        def __init__(self, on_found, on_lost=None) -> None:
            self._on_found = on_found
            self._on_lost = on_lost

        def add_service(self, zc, type_, name):  # noqa: N802 (zeroconf API)
            self._resolve(zc, type_, name)

        def update_service(self, zc, type_, name):  # noqa: N802
            self._resolve(zc, type_, name)

        def remove_service(self, zc, type_, name):  # noqa: N802
            if self._on_lost is not None:
                self._on_lost(instance_name(name))

        def _resolve(self, zc, type_, name) -> None:
            info = None
            for _ in range(3):
                try:
                    info = zc.get_service_info(type_, name, timeout=3000)
                except Exception:  # pragma: no cover - transient mDNS errors
                    info = None
                if info is not None:
                    break
            if info is None:
                return

            addresses = list(info.parsed_addresses() or [])
            ipv4 = [addr for addr in addresses if ":" not in addr]
            address = (ipv4 or addresses or [None])[0]
            if not address:
                return

            txt = info.properties or {}
            model = ""
            for key in (b"ty", b"model", b"mdl"):
                value = txt.get(key)
                if value:
                    model = value.decode("utf-8", "replace")
                    break

            self._on_found(
                DiscoveredCamera(
                    address=address,
                    guid=name,
                    model=model or instance_name(name),
                    port=info.port or PTPIP_PORT,
                )
            )


class MdnsDiscovery:
    """Continuously browse for ``_ptp._tcp.local`` services.

    ``on_found`` and ``on_lost`` are called from zeroconf's background threads,
    so callers that touch Qt must marshal back to the GUI thread themselves.
    """

    def __init__(self, on_found, on_lost=None) -> None:
        self._on_found = on_found
        self._on_lost = on_lost
        self._zeroconf = None
        self._browser = None

    def start(self) -> None:
        if not ZEROCONF_AVAILABLE:
            raise RuntimeError(
                "mDNS discovery requires the 'zeroconf' package (pip install zeroconf)"
            )
        self._zeroconf = Zeroconf()
        listener = _PtpServiceListener(self._on_found, self._on_lost)
        self._browser = ServiceBrowser(self._zeroconf, PTP_SERVICE_TYPE, listener)

    def stop(self) -> None:
        if self._browser is not None:
            try:
                self._browser.cancel()
            except Exception:  # pragma: no cover
                pass
            self._browser = None
        if self._zeroconf is not None:
            try:
                self._zeroconf.close()
            except Exception:  # pragma: no cover
                pass
            self._zeroconf = None


class MdnsAdvertiser:
    """Advertise a mock camera on ``_ptp._tcp.local`` (used by the mock server)."""

    def __init__(self, address: str, port: int, instance: str) -> None:
        self._address = address
        self._port = port
        self._instance = instance
        self._zeroconf = None
        self._info = None

    def start(self) -> None:
        if not ZEROCONF_AVAILABLE:
            raise RuntimeError("advertising requires the 'zeroconf' package")
        self._zeroconf = Zeroconf()
        self._info = ServiceInfo(
            PTP_SERVICE_TYPE,
            f"{self._instance}.{PTP_SERVICE_TYPE}",
            addresses=[socket.inet_aton(self._address or "127.0.0.1")],
            port=self._port,
            properties={b"ty": b"Canon EOS (mock)"},
        )
        self._zeroconf.register_service(self._info)

    def stop(self) -> None:
        if self._zeroconf is not None and self._info is not None:
            try:
                self._zeroconf.unregister_service(self._info)
            except Exception:  # pragma: no cover
                pass
        if self._zeroconf is not None:
            try:
                self._zeroconf.close()
            except Exception:  # pragma: no cover
                pass
        self._zeroconf = None
        self._info = None
