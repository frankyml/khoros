#!/usr/bin/env python3
"""
Prepare a local copy of a Harbor dataset for this machine: native (ARM) image builds behind a TLS-inspecting proxy.

Why: on Apple Silicon, x86 task images run under Rosetta, which exposes no AVX, and Claude Code's native Linux
binary crashes there; building each task's Dockerfile natively avoids emulation. Behind a TLS-inspecting proxy,
build steps (apt, git clone, curl) and the task's tests also need the proxy's root CA.

What changes: right after every FROM line, the Dockerfile copies certs/ca-bundle.pem (public roots + the proxy's
root CA) into the image and points the standard trust variables at it. Nothing else in the task changes, and
every arm runs the same patched task. The source dataset is left untouched.

Usage: python3 bench/harbor/prepare_dataset.py datasets/terminal-bench datasets/terminal-bench-local
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

HARBOR_DIR = Path(__file__).resolve().parent
BUNDLE_NAME = ".bench-ca-bundle.pem"
TRUST_LINES = [
    f"COPY {BUNDLE_NAME} /opt/bench-certs/ca-bundle.pem",
    "ENV SSL_CERT_FILE=/opt/bench-certs/ca-bundle.pem CURL_CA_BUNDLE=/opt/bench-certs/ca-bundle.pem "
    "REQUESTS_CA_BUNDLE=/opt/bench-certs/ca-bundle.pem PIP_CERT=/opt/bench-certs/ca-bundle.pem "
    "GIT_SSL_CAINFO=/opt/bench-certs/ca-bundle.pem NODE_EXTRA_CA_CERTS=/opt/bench-certs/ca-bundle.pem",
]
FROM_LINE = re.compile(r"^\s*FROM\s", re.IGNORECASE)


def patch_dockerfile(text: str) -> str:
    out = []
    for line in text.splitlines():
        out.append(line)
        if FROM_LINE.match(line):
            out.extend(TRUST_LINES)
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--bundle", type=Path, default=HARBOR_DIR / "certs" / "ca-bundle.pem")
    args = parser.parse_args()
    if not args.bundle.exists():
        parser.error(f"missing CA bundle: {args.bundle}")
    if args.dest.exists():
        shutil.rmtree(args.dest)
    shutil.copytree(args.source, args.dest)

    patched = 0
    for dockerfile in sorted(args.dest.glob("*/environment/Dockerfile")):
        dockerfile.write_text(patch_dockerfile(dockerfile.read_text(encoding="utf-8")), encoding="utf-8")
        shutil.copy2(args.bundle, dockerfile.parent / BUNDLE_NAME)
        patched += 1
    tasks = len(list(args.dest.glob("*/task.toml")))
    print(f"{tasks} tasks copied to {args.dest}; {patched} Dockerfiles patched for the CA bundle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
