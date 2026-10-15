"""Run the mock camera server standalone::

python -m canon_eos_utility.mock --host 0.0.0.0 --port 15740
"""

from __future__ import annotations

import argparse
import time

from .server import MockCameraServer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock Canon EOS camera (PTP/IP)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15740)
    parser.add_argument("--model", default="Canon EOS 70D (mock)")
    parser.add_argument(
        "--advertise",
        action="store_true",
        help="announce the mock camera over mDNS (_ptp._tcp) for auto-discovery",
    )
    args = parser.parse_args(argv)

    server = MockCameraServer(host=args.host, port=args.port, model=args.model)
    server.start(advertise=args.advertise)
    print(f"Mock Canon camera listening on {server.host}:{server.port} ({args.model})")
    if args.advertise:
        print("Advertising _ptp._tcp via mDNS — the GUI will auto-connect.")
    print("Connect the GUI to this address. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
