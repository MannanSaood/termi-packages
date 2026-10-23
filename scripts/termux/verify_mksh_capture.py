#!/usr/bin/env python3
"""Verify the initializer emitted by the Kotlin test in real host mksh.

This is shell/protocol verification, not Android PTY or device latency evidence.
"""
import base64
import json
from pathlib import Path
import subprocess
import time

root = Path("/home/builder/mksh-fixture")
capture = root / "capture.state"
expected = {}
for line in (root / "expected.tsv").read_text().splitlines():
    name, exported, value = line.split("\t")
    expected[name] = (exported, base64.b64decode(value).decode())
measurements = []
for _ in range(3):
    start = time.monotonic()
    result = subprocess.run(["/bin/mksh", str(root / "init.mksh")],
                            cwd=root, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                            capture_output=True, timeout=10)
    assert result.returncode == 0 and b"mksh-fixture-ready" in result.stdout, result
    fields = capture.read_bytes().decode().split("\0")
    assert fields[:2] == ["TRS1", str(root)] and fields[-3:] == ["", "END", ""], fields
    actual = {fields[i]: (fields[i + 1], fields[i + 2]) for i in range(2, len(fields) - 3, 3)}
    for name, value in expected.items():
        assert actual[name] == value, (name, actual.get(name), value)
    assert not (root / "accidental-execution").exists()
    assert not (root / "replayed-command").exists()
    measurements.append(round((time.monotonic() - start) * 1000, 3))
before = capture.read_bytes()
temporary = root / "capture.state.tmp"
temporary.mkdir()
try:
    failed = subprocess.run(["/bin/mksh", str(root / "init.mksh")],
                            cwd=root, env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=10)
    assert b"mksh-fixture-ready" not in failed.stdout
    assert capture.read_bytes() == before and (root / "capture.error").is_file()
finally:
    temporary.rmdir()
print(json.dumps({"shell": "Linux mksh", "correct_runs": 3, "literal_variables": len(expected),
                  "failure_preserves_capture": True, "initializer_host_ms": measurements,
                  "device_performance": "unverified"}, indent=2))
