"""Records a human check. Only a person runs this against a real pack; coding agents and review pipelines never do."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from tutor.content import load_pack
from tutor.review import ReviewGateError, record_error, record_pass, record_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--packs-dir", type=Path)
    parser.add_argument("--by", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pass", dest="passed", nargs="+")
    group.add_argument("--error", dest="errored", nargs="+")
    group.add_argument("--release", action="store_true")
    parser.add_argument("--note", default="")
    parser.add_argument("--scope-note", default="")
    args = parser.parse_args(argv)
    try:
        pack = load_pack(args.pack, args.packs_dir)
        if args.passed:
            record_pass(pack, args.passed, args.by, args.note)
            for item_id in args.passed:
                print(f"signed off {item_id}")
        elif args.errored:
            record_error(pack, args.errored, args.by, args.note)
            for item_id in args.errored:
                print(f"recorded error {item_id}")
        else:
            release = record_release(pack, args.by, args.scope_note)
            print(f"release signed off {release.pack_id} {release.version}")
        return 0
    except ReviewGateError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
