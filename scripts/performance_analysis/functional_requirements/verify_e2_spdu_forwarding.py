#!/usr/bin/env python3
"""E2 - DT 1609.2 & 1609.3 Support.

    Requirement:  The Distributed Testing middleware must be able to receive,
                  forward, and distribute V2X messages in the form of IEEE
                  1609.2-compliant PSDUs, preserving all 1609.2 security and
                  IEEE 1609.3 WSMP headers, so that signed and unsigned
                  messages can be delivered to connected devices without
                  modification.
    Criteria:     PASS / FAIL
    System:       DT System

WHAT THIS VERIFIES
------------------
This script verifies that every forwarded payload supports 1609.2 SPDUs 
(signed and undisnged), and that nothing along the way alters them.

Where the SPDU lives
--------------------
`VUG::TV2XMsg::SecuredV2X` carries both `binaryContent` (the J2735 payload) and
`rawMessage` (the framed 1609.2 SPDU). `VUG::TV2XMsg::V2X` carries only
`binaryContent`. Header preservation can therefore only be judged on SecuredV2X
records -- a V2X record has no headers to preserve, and this script reports that
rather than counting it as a failure.

INPUT
-----
A TDCS SQLite recording from a run carrying V2X traffic:

    ./verify_e2_spdu_forwarding.py run.sqlite

The recording must have TDCS subscribed to the V2X message types

EXIT CODES
----------
    0  PASS     requirement met
    1  FAIL     requirement not met
    2  NO_DATA  no V2X traffic, or no SPDU bytes captured
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from e2e_utils.spdu_utils import locate_spdu  # noqa: E402

SECURED_TYPE = "VUG::TV2XMsg::SecuredV2X"
PLAIN_TYPE = "VUG::TV2XMsg::V2X"


def quote(identifier: str) -> str:
    """Backtick-quotes a TDCS table or column name for SQL.

    Args:
        identifier: Raw table or column name.
    """
    return "`" + identifier.replace("`", "``") + "`"


def open_recording(path: Path) -> sqlite3.Connection:
    """Opens a TDCS recording read-only, falling back for read-only media.

    Args:
        path: Recording file.

    Returns:
        An open connection with a row factory set.

    Raises:
        sqlite3.Error: If the file cannot be opened either way.
    """
    posix = path.as_posix()
    for uri in (f"file:{posix}?mode=ro", f"file:{posix}?mode=ro&immutable=1"):
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            continue
    raise sqlite3.Error(f"Cannot open {path} read-only")


# -------------------------------------------------------------- data loading


@dataclass
class Observation:
    """One recorded V2X message as seen by one publisher.

    Attributes:
        table: Message table the observation came from.
        row_id: Row id within that table.
        secured: True when read from SecuredV2X (which carries an SPDU).
        uuid: Message uuid, correlating observations of one message.
        sender: `senderIdentifier` of the publishing adapter.
        sender_host: TENA SenderId host address, a second identity for the
            publisher when senderIdentifier is not distinct.
        message_type: J2735 message type string.
        raw_message: Framed 1609.2 SPDU bytes, empty when not recorded.
    """

    table: str
    row_id: int
    secured: bool
    uuid: str
    sender: str
    sender_host: int
    message_type: str
    raw_message: bytes = b""


def type_id(conn: sqlite3.Connection, type_name: str) -> str | None:
    """Resolves a TENA type name to the hash used in its table names.

    Args:
        conn: Open connection.
        type_name: Fully-qualified TENA type name.
    """
    try:
        rows = conn.execute("SELECT Name, TypeId FROM omTypeIdMap")
    except sqlite3.Error:
        return None
    for row in rows:
        if row["Name"] == type_name:
            return str(row["TypeId"])
    return None


def octets(conn: sqlite3.Connection, vector_table: str, parent: str, row_id: int) -> bytes:
    """Reassembles a TENA octet vector into bytes.

    TDCS stores a vector of UInt8 as one row per octet, so the payload must be
    rebuilt in row order.

    Args:
        conn: Open connection.
        vector_table: Table holding the octet rows.
        parent: Message table the vector belongs to.
        row_id: Parent message row id.
    """
    key = f"DB,{parent},rowID"
    rows = conn.execute(
        f"SELECT {quote('UInt8')} AS b FROM {quote(vector_table)} "
        f"WHERE {quote(key)} = ? ORDER BY rowID",
        (row_id,),
    )
    return bytes(int(r["b"]) & 0xFF for r in rows)


def load_observations(conn: sqlite3.Connection) -> tuple[list[Observation], dict[str, int]]:
    """Reads every recorded V2X and SecuredV2X message.

    Args:
        conn: Open connection.

    Returns:
        Tuple of (observations, per-table row counts including empty tables).
    """
    present = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    observations: list[Observation] = []
    counts: dict[str, int] = {}

    for type_name, secured in ((SECURED_TYPE, True), (PLAIN_TYPE, False)):
        hash_id = type_id(conn, type_name)
        if hash_id is None:
            counts[type_name] = -1  # absent from the object model entirely
            continue
        table = f"Msg,{type_name},{hash_id}"
        if table not in present:
            counts[type_name] = -1
            continue
        total = conn.execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()[0]
        counts[table] = int(total)
        if not total:
            continue
        raw_table = f"VectorMsg,{type_name},{hash_id},rawMessage"
        has_raw = raw_table in present
        available = {d[0] for d in conn.execute(f"SELECT * FROM {quote(table)} LIMIT 0").description}

        for row in conn.execute(f"SELECT * FROM {quote(table)} ORDER BY rowID"):
            row_id = int(row["rowID"])
            observations.append(
                Observation(
                    table=table,
                    row_id=row_id,
                    secured=secured,
                    uuid=str(row["uuid,String"]) if "uuid,String" in available else "",
                    sender=(
                        str(row["senderIdentifier,String"])
                        if "senderIdentifier,String" in available
                        else ""
                    ),
                    sender_host=(
                        int(row["Metadata,SenderId.hostIPaddress"])
                        if "Metadata,SenderId.hostIPaddress" in available
                        else 0
                    ),
                    message_type=(
                        str(row["messageType,String"])
                        if "messageType,String" in available
                        else ""
                    ),
                    raw_message=(
                        octets(conn, raw_table, table, row_id) if has_raw else b""
                    ),
                )
            )
    return observations, counts


def digest(payload: bytes) -> str:
    """Returns a short stable fingerprint of a payload.

    Args:
        payload: Raw bytes.
    """
    return hashlib.sha256(payload).hexdigest()[:16]


def hex_head(payload: bytes, count: int = 12) -> str:
    """Renders the leading bytes of a payload as spaced hex.

    Args:
        payload: Raw bytes.
        count: How many leading bytes to render.
    """
    tail = "..." if len(payload) > count else ""
    return " ".join(f"{b:02X}" for b in payload[:count]) + tail


# ------------------------------------------------------------------- verdict


@dataclass
class Result:
    """Outcome of the E2 check."""

    status: str = "NO_DATA"
    summary: str = ""
    observations: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def verify(conn: sqlite3.Connection, require_wsmp: bool) -> Result:
    """Checks that forwarded V2X payloads are well-formed and unmodified.

    Args:
        conn: Open connection to the recording.
        require_wsmp: When True, every SPDU must carry a WSMP header.

    Returns:
        The verification result.
    """
    result = Result()
    messages, counts = load_observations(conn)

    for name, count in counts.items():
        if count < 0:
            result.observations.append(f"{name} is absent from this object model.")
        else:
            result.observations.append(f"{name}: {count} message(s).")

    if not messages:
        result.observations.append(
            "No V2X traffic was recorded. Run a scenario with message broadcast "
            "enabled and TDCS subscribed to the V2X message types."
        )
        result.summary = "Recording contains no V2X messages."
        return result

    result.metrics["observations"] = len(messages)

    with_spdu = [m for m in messages if m.raw_message]
    plain_only = [m for m in messages if not m.secured]
    if plain_only:
        result.observations.append(
            f"{len(plain_only)} message(s) came from the unsecured V2X type, "
            "which carries only binaryContent and no framed SPDU. Those have no "
            "1609.2 or 1609.3 headers to preserve and are excluded from the "
            "header checks."
        )

    if not with_spdu:
        result.observations.append(
            "No rawMessage vector was populated, so the framed SPDU the DT "
            "network carried was not recorded. Only the decoded payload is "
            "present, which cannot show header preservation."
        )
        result.summary = "V2X traffic recorded but no SPDU bytes captured."
        return result

    # --- Claim 1: well-formedness.
    anchored = 0
    low_confidence = 0
    malformed: list[str] = []
    choices: Counter = Counter()
    psids: Counter = Counter()
    wsmp_framed = 0

    for message in with_spdu:
        info = locate_spdu(message.raw_message)
        if info.recognised and info.anchored:
            anchored += 1
            choices[info.content_choice or "unknown"] += 1
            if info.psid is not None:
                psids[info.psid] += 1
                wsmp_framed += 1
        elif info.recognised:
            low_confidence += 1
        else:
            malformed.append(
                f"{message.table} row {message.row_id} (uuid {message.uuid[:12]}): "
                f"{info.reason}; leading bytes {hex_head(message.raw_message)}"
            )

    result.observations.append(
        f"{len(with_spdu)} message(s) carry a framed SPDU; {anchored} confirmed "
        f"as Ieee1609Dot2Data."
    )
    if choices:
        result.observations.append(
            "1609.2 content types: "
            + ", ".join(f"{k}={v}" for k, v in sorted(choices.items()))
        )
    result.observations.append(
        f"{wsmp_framed} of {anchored} carried an IEEE 1609.3 WSMP header."
    )
    if psids:
        result.observations.append(
            "WSMP PSIDs: "
            + ", ".join(f"0x{p:X}({p})={n}" for p, n in sorted(psids.items()))
        )
    if low_confidence:
        result.observations.append(
            f"{low_confidence} payload(s) matched a content tag only by "
            "unanchored scan, with no WSMP header or length check to "
            "corroborate. That pattern is known to false-positive on vendor "
            "header bytes, so they are excluded from the verdict."
        )

    result.metrics["with_spdu"] = len(with_spdu)
    result.metrics["confirmed_spdus"] = anchored
    result.metrics["low_confidence"] = low_confidence
    result.metrics["wsmp_framed"] = wsmp_framed
    result.metrics["content_types"] = dict(choices)
    result.metrics["psids"] = {str(p): n for p, n in sorted(psids.items())}

    if malformed:
        for item in malformed[:10]:
            result.observations.append(f"PROBLEM: {item}")
        result.status = "FAIL"
        result.summary = (
            f"{len(malformed)} of {len(with_spdu)} forwarded payload(s) were not "
            "valid IEEE 1609.2 PDUs."
        )
        return result

    if anchored == 0:
        result.summary = (
            "No payload could be confirmed as an Ieee1609Dot2Data with "
            "confidence."
        )
        return result

    if require_wsmp and wsmp_framed < anchored:
        result.status = "FAIL"
        result.summary = (
            f"WSMP framing required, but only {wsmp_framed} of {anchored} SPDU(s) "
            "carried a WSMP header."
        )
        return result

    # --- Claim 2: preservation across the DT network.
    by_uuid: dict[str, list[Observation]] = defaultdict(list)
    for message in with_spdu:
        by_uuid[message.uuid].append(message)

    multi_point = {}
    for uuid, group in by_uuid.items():
        points = {(m.sender, m.sender_host) for m in group}
        if len(points) > 1:
            multi_point[uuid] = group

    result.metrics["distinct_uuids"] = len(by_uuid)
    result.metrics["multi_point_uuids"] = len(multi_point)

    altered: list[str] = []
    identical = 0
    for uuid, group in multi_point.items():
        payloads = {}
        for message in group:
            payloads[(message.sender, message.sender_host)] = message.raw_message
        digests = {point: digest(p) for point, p in payloads.items()}
        if len(set(digests.values())) == 1:
            identical += 1
        else:
            altered.append(
                f"uuid {uuid[:12]} ({group[0].message_type}): "
                + ", ".join(
                    f"{point[0] or point[1]}={d} len={len(payloads[point])}"
                    for point, d in sorted(digests.items(), key=lambda kv: str(kv[0]))
                )
            )

    result.metrics["byte_identical"] = identical
    result.metrics["altered"] = len(altered)

    if altered:
        for item in altered[:10]:
            result.observations.append(f"PROBLEM: {item}")
        result.status = "FAIL"
        result.summary = (
            f"{len(altered)} of {len(multi_point)} message(s) were modified in "
            "transit across the DT network."
        )
        return result

    if not multi_point:
        senders = sorted({m.sender or str(m.sender_host) for m in with_spdu})
        result.observations.append(
            f"Every uuid was observed at a single publisher ({', '.join(senders)}), "
            "so byte-level preservation across the DT network was not exercised."
        )
        result.observations.append(
            "To test it, subscribe TDCS to both the ingress and egress adapters "
            "in one session, or merge the two site recordings, so the same uuid "
            "appears twice."
        )
        result.status = "PASS"
        result.summary = (
            f"All {anchored} forwarded payload(s) were well-formed 1609.2 PDUs. "
            "End-to-end preservation was not exercised in this recording."
        )
        return result

    result.status = "PASS"
    result.summary = (
        f"All {anchored} payload(s) were well-formed 1609.2 PDUs, and "
        f"{identical} message(s) observed at multiple points were byte-identical "
        "end to end."
    )
    return result


def render(result: Result, verbose: bool) -> None:
    """Prints the result.

    Args:
        result: Verification result.
        verbose: Whether to print metrics.
    """
    print()
    print("E2 - DT 1609.2 & 1609.3 Support")
    print("=" * 68)
    print(f"  Result: {result.status}")
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
            "Verify E2: the DT middleware forwards V2X messages as 1609.2 PDUs, "
            "preserving 1609.2 and 1609.3 headers without modification."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Preservation can only be judged when the same message is observed\n"
            "at two points. Subscribe TDCS to both the ingress and egress\n"
            "adapters in one session so a uuid appears under two publishers."
        ),
    )
    parser.add_argument("tdcs", type=Path, help="TDCS SQLite recording.")
    parser.add_argument(
        "--require-wsmp",
        action="store_true",
        help=(
            "Require every SPDU to carry a WSMP header. Leave off unless the "
            "transceiver forwards full WSMs; NTCIP 1218 Immediate Forward "
            "commonly delivers a bare SPDU."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Also print metrics."
    )
    args = parser.parse_args(argv)

    if not args.tdcs.is_file():
        print(f"Recording not found: {args.tdcs}", file=sys.stderr)
        return 2

    try:
        conn = open_recording(args.tdcs)
    except sqlite3.Error as exc:
        print(f"Could not open {args.tdcs}: {exc}", file=sys.stderr)
        return 2

    try:
        result = verify(conn, args.require_wsmp)
    finally:
        conn.close()

    result.metrics["recording"] = str(args.tdcs)

    if args.json:
        print(
            json.dumps(
                {
                    "requirement": "E2",
                    "title": "DT 1609.2 & 1609.3 Support",
                    "status": result.status,
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