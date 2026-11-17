"""PoC 01: read simulated RPM / speed / coolant temperature from OCTAVE.

Uses the official octave_client SDK (MIT) straight from the third-party checkout,
read-only. Run:  python -B -I probe.py [--sdk PATH] [--port 9876]
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_SDK = Path(__file__).resolve().parents[3] / "externals" / "octave" / "sdk" / "python"
PIDS = ["RPM", "SPEED", "COOLANT_TEMP"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", default=str(DEFAULT_SDK))
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    sys.dont_write_bytecode = True  # never write __pycache__ into the third-party tree
    sys.path.insert(0, args.sdk)
    from octave_client import Client

    with Client("127.0.0.1", args.port, timeout=10) as octave:
        hello = octave.hello()
        print("hello:", json.dumps({k: hello[k] for k in hello if k != "objects"}, default=str))
        print("objects:", len(hello.get("objects", [])))

        for pid in PIDS:
            info = octave.call("parameterCatalog", "info", pid)
            print(f"catalog {pid}: title={info.get('title')!r} unit={info.get('unit')!r} "
                  f"range=({info.get('min')}, {info.get('max')})")

        print("one-shot get paramStore:", {p: octave.get("paramStore", p) for p in PIDS})

        octave.subscribe("paramStore", properties=PIDS, throttle_ms=250)
        n = 0
        for event in octave.events(timeout=10):
            if event.get("event") != "params":
                continue
            print("event:", json.dumps(event["values"]))
            n += 1
            if n >= args.samples:
                break
        if n == 0:
            print("NO params events received")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
