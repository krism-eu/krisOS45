#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys


def run_git(root: pathlib.Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write one deterministic text snapshot for an exact Git commit.")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--display-ref", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    output = pathlib.Path(args.output).resolve()
    commit = run_git(root, "rev-parse", f"{args.ref}^{{commit}}").decode("ascii").strip()
    tree = run_git(root, "rev-parse", f"{commit}^{{tree}}").decode("ascii").strip()
    entries = run_git(root, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as out:
        header = [
            "# repository source snapshot",
            f"# repository: {args.repository}",
            f"# ref: {args.display_ref or args.ref}",
            f"# commit: {commit}",
            f"# tree: {tree}",
        ]
        if args.version:
            header.append(f"# version-release: {args.version}")
        header.extend([
            "# scope: exact tracked Git tree at the commit above",
            "# text files are embedded verbatim; binary blobs are represented by SHA256 markers",
            "",
        ])
        out.write(("\n".join(header) + "\n").encode("utf-8"))

        for raw in entries:
            if not raw:
                continue
            metadata, path_raw = raw.split(b"\t", 1)
            mode_raw, object_type_raw, object_sha_raw = metadata.split(b" ", 2)
            if object_type_raw != b"blob":
                raise RuntimeError(f"unexpected Git object type: {object_type_raw!r}")
            path_text = path_raw.decode("utf-8")
            mode = mode_raw.decode("ascii")
            object_sha = object_sha_raw.decode("ascii")
            data = run_git(root, "cat-file", "blob", object_sha)
            sha256 = hashlib.sha256(data).hexdigest()
            out.write((f"===== FILE: {path_text} | mode={mode} | git={object_sha} | sha256={sha256} | size={len(data)} =====\n").encode("utf-8"))
            if mode == "120000":
                out.write(f"[[SYMLINK -> {data.decode('utf-8', errors='replace')}]]\n\n".encode("utf-8"))
                continue
            binary = b"\0" in data[:8192]
            if not binary:
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    binary = True
            if binary:
                out.write(f"[[BINARY BLOB OMITTED · sha256={sha256} · {len(data)} bytes]]\n\n".encode("utf-8"))
                continue
            out.write(text.encode("utf-8"))
            if data and not data.endswith(b"\n"):
                out.write(b"\n")
            out.write(b"\n")

    print(f"snapshot={output}")
    print(f"commit={commit}")
    print(f"tree={tree}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError, UnicodeError) as exc:
        print(f"source_snapshot: {exc}", file=sys.stderr)
        raise SystemExit(1)
