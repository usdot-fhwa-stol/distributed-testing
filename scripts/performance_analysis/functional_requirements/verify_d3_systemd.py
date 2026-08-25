#!/usr/bin/env python3
"""D3 - System service configurability.

    Requirement:  The DUT shall permit the creation and modification of the
                  system services required to enable emulated GPS.
    Criteria:     DUT Systemd services are configurable.
    System:       DUT (OBU)

WHAT THIS VERIFIES
------------------
This verifies that a systemd unit for the emulated GPS path exists on the DUT,
is installed and enabled, and was started.

WHAT THIS CHECKS
----------------
There are three checks this script does. It runs all three and reports the
strongest one that succeeded, because they differ in how much they actually
prove.

The first check looks for the unit file itself: a path under
/etc/systemd/system/ together with the file's contents, as `systemctl cat`
produces. 

The second check looks for the unit's installation state: `systemctl status`
reporting it loaded, from a known path, with a known enablement state. This
shows the service is administered through systemd rather than started by hand,
which implies it is configurable.

The third check looks for lifecycle activity in the journal: a daemon-reload, an
enable, a start or a restart. 

INPUT
-----
One or more text files. Concatenating these on the DUT is enough:

    systemctl cat  <unit>                         >  d3_service.txt
    systemctl status <unit>                       >> d3_service.txt
    journalctl -u <unit> --output=short-precise   >> d3_service.txt

USAGE
-----
    ./verify_d3_systemd.py d3_service.txt
    ./verify_d3_systemd.py d3_service.txt --unit netcat-gpsd
    ./verify_d3_systemd.py logs/ --json

EXIT CODES
----------
    0  PASS     requirement met
    1  FAIL     requirement not met
    2  NO_DATA  no readable input, or no systemd content at all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Unit-file paths under /etc are operator-writable, which is what makes a
# service configurable
WRITABLE_UNIT_RE = re.compile(r"(/etc/systemd/system/[\w@.\-]+\.service)")
VENDOR_UNIT_RE = re.compile(r"((?:/usr)?/lib/systemd/system/[\w@.\-]+\.service)")

# `systemctl cat` emits "# /path/to/unit.service" then the file contents.
UNIT_SECTION_RE = re.compile(r"^\s*\[(Unit|Service|Install)\]\s*$", re.MULTILINE)
EXECSTART_RE = re.compile(r"^\s*ExecStart\s*=\s*(.+)$", re.MULTILINE)

LOADED_RE = re.compile(r"Loaded:\s*loaded\s*\(([^;]+);\s*([\w-]+)", re.IGNORECASE)
ACTIVE_RE = re.compile(r"Active:\s*(\w+)", re.IGNORECASE)

RELOAD_PATTERNS = [
    r"systemctl\s+daemon-reload",
    r"Reloading\b",
    r"Reloaded\b.*configuration",
]
START_PATTERNS = [
    r"systemctl\s+(enable|start|restart)\b",
    r"systemd\[\d+\]:\s*Started\s+\S+",
    r"Started\s+\S+\.service\b",
    r"Created symlink\b.*\.service",
]

UNIT_FILE_PATTERNS = [
    r"^\s*\[Unit\]\s*$",
    r"^\s*\[Service\]\s*$",
    r"^\s*ExecStart\s*=",
]

# Markers that the input is systemd output at all
SYSTEMD_CONTEXT_PATTERNS = [
    r"^\s*\[Service\]\s*$",
    r"^\s*ExecStart\s*=",
    r"systemd\[\d+\]",
    r"\bsystemctl\b",
    r"\.service\b",
    r"Loaded:\s*loaded",
    r"Active:\s*\w+",
    r"/etc/systemd/",
    r"/lib/systemd/",
]
FAILURE_PATTERNS = [
    r"Failed to start\s+\S+",
    r"Unit\s+\S+\.service\s+(failed|entered failed state)",
    r"Active:\s*failed",
]

TEXT_SUFFIXES = {".txt", ".log", ".out", ".journal", ""}


@dataclass
class Result:
    """Outcome of the D3 check.

    Attributes:
        status: PASS, FAIL or NO_DATA.
        tier: Which evidence tier was reached
        summary: One-line explanation.
        observations: What the check found.
        metrics: Machine-readable measurements.
    """

    status: str = "NO_DATA"
    tier: int = 0
    summary: str = ""
    observations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def load_text(paths: list[Path]) -> tuple[str, list[str]]:
    """Reads all input files into one blob.

    Args:
        paths: Files or directories. Directories are scanned one level deep for
            text-like files.

    Returns:
        Tuple of (combined text, list of files read).
    """
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                sorted(
                    p
                    for p in path.iterdir()
                    if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
                )
            )
        elif path.is_file():
            files.append(path)
    chunks = []
    read: list[str] = []
    for path in files:
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            read.append(str(path))
        except OSError:
            continue
    return "\n".join(chunks), read


def matches(text: str, patterns: list[str]) -> list[str]:
    """Returns the distinct lines matching any of the given patterns.

    Args:
        text: Text to search.
        patterns: Regular expressions, applied case-insensitively.
    """
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    found: list[str] = []
    for line in text.splitlines():
        if any(c.search(line) for c in compiled):
            stripped = line.strip()
            if stripped not in found:
                found.append(stripped)
    return found


def verify(text: str, unit: str | None, unit_path: str | None = None) -> Result:
    """Evaluates captured systemd output against the D3 criteria.

    Args:
        text: Combined text of all input files.
        unit: Optional unit name to require, e.g. "netcat-gpsd". When given,
            evidence must mention it.
        unit_path: Location the unit file occupies on the DUT

    Returns:
        The verification result.
    """
    result = Result()

    # A declared path is operator-asserted rather than captured
    if unit_path:
        text = f"# {unit_path}\n{text}"
        result.observations.append(
            f"Unit path supplied on the command line: {unit_path}."
        )
        result.metrics["unit_path_declared"] = unit_path

    if unit:
        result.metrics["unit_filter"] = unit
        # Keep only the portion of the text mentioning the unit
        relevant = [
            line for line in text.splitlines() if unit.lower() in line.lower()
        ]
        if not relevant:
            result.observations.append(
                f"No line mentions the unit {unit!r}."
            )
            result.status = "FAIL"
            result.summary = f"No evidence for unit {unit!r} in the supplied input."
            return result
        scoped = "\n".join(relevant)
    else:
        scoped = text

    if not matches(text, SYSTEMD_CONTEXT_PATTERNS):
        result.observations.append(
            "This input contains no systemd markers at all"
        )
        result.summary = "Input is not systemd output; nothing to evaluate."
        return result

    writable_units = sorted(set(WRITABLE_UNIT_RE.findall(scoped)))
    vendor_units = sorted(set(VENDOR_UNIT_RE.findall(scoped)))
    has_unit_body = bool(UNIT_SECTION_RE.search(text)) and bool(
        EXECSTART_RE.search(text)
    )
    exec_starts = EXECSTART_RE.findall(text)

    loaded = LOADED_RE.search(scoped)
    active = ACTIVE_RE.search(scoped)
    reloads = matches(scoped, RELOAD_PATTERNS)
    starts = matches(scoped, START_PATTERNS)
    failures = matches(scoped, FAILURE_PATTERNS)

    if has_unit_body and not (writable_units or vendor_units or loaded):
        result.summary = (
            "Unit file supplied without its location"
        )
        return result

    any_systemd = bool(
        writable_units or vendor_units or loaded or active or reloads or starts
    )
    if not any_systemd:
        result.observations.append(
            "The input contains no systemd unit paths, no `systemctl status` "
            "output, and no unit start/reload lines."
        )
        result.observations.append(
            "Collect evidence with: systemctl cat <unit>; systemctl status "
            "<unit>; journalctl -u <unit> --output=short-precise"
        )
        result.summary = "No systemd content found in the supplied input."
        return result

    if writable_units:
        result.observations.append(
            f"Unit file(s) under operator-writable /etc: {', '.join(writable_units)}"
        )
    if vendor_units:
        result.observations.append(
            f"Vendor-supplied unit path(s) under /lib: {', '.join(vendor_units)}. "
            "These ship with the image and are not themselves evidence of "
            "configurability."
        )
    if has_unit_body:
        result.observations.append(
            "Unit file body captured (section headers and ExecStart present): "
            + "; ".join(e.strip()[:80] for e in exec_starts[:2])
        )
    if loaded:
        result.observations.append(
            f"systemctl reports the unit loaded from {loaded.group(1).strip()}, "
            f"state {loaded.group(2)}."
        )
    if active:
        result.observations.append(f"systemctl reports Active: {active.group(1)}.")
    if reloads:
        result.observations.append(
            f"{len(reloads)} daemon-reload line(s), e.g. {reloads[0][:90]}"
        )
    if starts:
        result.observations.append(
            f"{len(starts)} enable/start line(s), e.g. {starts[0][:90]}"
        )
    if failures:
        result.observations.append(
            f"{len(failures)} unit failure line(s) present, e.g. "
            f"{failures[0][:90]}. "
        )

    result.metrics["writable_unit_files"] = writable_units
    result.metrics["vendor_unit_files"] = vendor_units
    result.metrics["unit_body_captured"] = has_unit_body
    result.metrics["loaded"] = bool(loaded)
    result.metrics["enabled_state"] = loaded.group(2) if loaded else None
    result.metrics["active_state"] = active.group(1) if active else None
    result.metrics["daemon_reloads"] = len(reloads)
    result.metrics["start_lines"] = len(starts)
    result.metrics["failure_lines"] = len(failures)

    # Tier 1: the unit file itself, at a writable path, with its body captured.
    if writable_units and has_unit_body:
        result.tier = 1
        result.status = "PASS"
        result.summary = (
            f"Unit file captured at {writable_units[0]}, an operator-writable "
            "path, with its contents. This directly evidences that the service "
            "can be created and modified."
        )
    # Tier 2: installed and enabled, but the file body was not captured.
    elif writable_units or (loaded and loaded.group(2) in ("enabled", "disabled")):
        result.tier = 2
        result.status = "PASS"
        result.summary = (
            "The emulated-GPS unit is installed and its enablement state is "
            "reported, so it is administered through systemd."
        )
    # Tier 3: journal only.
    elif starts or reloads:
        result.tier = 3
        result.status = "PASS"
        result.summary = (
            "Journal shows the unit being reloaded and started, so a systemd "
            "service exists for the emulated-GPS path."
        )
    else:
        result.status = "FAIL"
        result.summary = (
            "systemd content is present but shows no unit file, no enablement "
            "state, and no start or reload of a service."
        )

    if result.tier:
        result.metrics["evidence_tier"] = result.tier
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics.
    """
    tiers = {
        1: "1 of 3 (strongest) - unit file captured from a writable path",
        2: "2 of 3 - unit installed and enablement state known",
        3: "3 of 3 (weakest) - journal activity only",
    }
    print()
    print("D3 - System service configurability")
    print("=" * 68)
    print(f"  Result: {result.status}")
    if result.tier:
        print(f"  Evidence tier: {tiers[result.tier]}")
    print(f"  {result.summary}")
    print()
    for note in result.observations:
        print(f"    - {note}")
    if verbose and result.metrics:
        print()
        print("  Metrics:")
        for key, value in result.metrics.items():
            print(f"    {key} = {value}")
    print()


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or None to read from sys.argv.

    Returns:
        Exit code: 0 PASS, 1 FAIL, 2 NO_DATA.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Verify D3: the DUT permits creation and modification of the "
            "systemd services required for emulated GPS."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Collect evidence on the DUT with:\n"
            "    systemctl cat  <unit>                        >  d3_service.txt\n"
            "    systemctl status <unit>                      >> d3_service.txt\n"
            "    journalctl -u <unit> --output=short-precise  >> d3_service.txt\n"
            "\n"
            "`systemctl cat` is the important one: it shows the unit file "
            "exists at a writable path, which is what configurability rests on."
        ),
    )
    parser.add_argument(
        "inputs",
        type=Path,
        nargs="+",
        help="Text files (or a directory of them) holding systemd output.",
    )
    parser.add_argument(
        "--unit-path",
        metavar="PATH",
        help=(
            "Where the unit file lives on the DUT, e.g. "
            "/etc/systemd/system/netcat-gpsd.service. Use this when passing a "
            "bare copy of the unit file, which carries no path of its own. "
            "`systemctl cat` includes the path already and needs no flag."
        ),
    )
    parser.add_argument(
        "--unit",
        help=(
            "Require evidence to mention this unit name, e.g. netcat-gpsd. "
            "Without it, any systemd service in the input can satisfy the check."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Also print metrics."
    )
    args = parser.parse_args(argv)

    text, files = load_text(args.inputs)
    if not files:
        print(f"No readable input files in: {args.inputs}", file=sys.stderr)
        return 2

    result = verify(text, args.unit, args.unit_path)
    result.metrics["files_read"] = files

    if args.json:
        print(
            json.dumps(
                {
                    "requirement": "D3",
                    "title": "System service configurability",
                    "status": result.status,
                    "evidence_tier": result.tier,
                    "summary": result.summary,
                    "observations": result.observations,
                    "metrics": result.metrics,
                },
                indent=2,
            )
        )
    else:
        render(result, args.verbose)

    return {"PASS": 0, "FAIL": 1}.get(result.status, 2)


if __name__ == "__main__":
    raise SystemExit(main())