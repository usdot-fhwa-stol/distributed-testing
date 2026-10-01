"""Locate IEEE 1609.2 SPDUs in raw payloads, bare or inside an IEEE 1609.3 WSMP frame."""

from __future__ import annotations

from dataclasses import dataclass

PROTOCOL_VERSION_3 = 0x03
CONTENT_CHOICES = {
    0x80: "unsecuredData",
    0x81: "signedData",
    0x82: "encryptedData",
    0x83: "signedCertificateRequest",
}
WSMP_ETHERTYPE = b"\x88\xDC"

# How far in to look for a bare WSMP N-header. Small, because every candidate is
# still validated against its own declared length.
WSMP_PREFIX_SCAN = 8
# Upper bound for the low-confidence fallback scan, used only for reporting.
FALLBACK_SCAN_LIMIT = 128


@dataclass
class SpduInfo:
    """Where and what the SPDU in a payload is.

    Attributes:
        recognised: True when an Ieee1609Dot2Data was located.
        content_choice: Name of the content CHOICE alternative.
        is_signed: True when the content is signedData.
        spdu_offset: Byte offset of the SPDU within the payload.
        psid: PSID from the WSMP header, when present.
        wsm_length: WSM length declared in the WSMP header, when present.
        anchored: True when found at offset 0 or behind a length-validated WSMP
            header; False for an unanchored byte-pattern match.
        reason: Why the payload was not recognised, when applicable.
    """

    recognised: bool
    content_choice: str | None = None
    is_signed: bool = False
    spdu_offset: int = 0
    psid: int | None = None
    wsm_length: int | None = None
    anchored: bool = False
    reason: str = ""


def decode_psid(payload: bytes, offset: int) -> tuple[int, int] | None:
    """Decode an IEEE 1609 p-encoded PSID.

    Args:
        payload: Buffer to read from.
        offset: Index of the first PSID octet.

    Returns:
        (psid, octets consumed), or None if truncated.
    """
    if offset >= len(payload):
        return None
    first = payload[offset]
    if first < 0x80:
        width, mask = 1, 0x7F
    elif first < 0xC0:
        width, mask = 2, 0x3F
    elif first < 0xE0:
        width, mask = 3, 0x1F
    else:
        width, mask = 4, 0x0F
    if offset + width > len(payload):
        return None
    value = first & mask
    for i in range(1, width):
        value = (value << 8) | payload[offset + i]
    return value, width


def parse_wsmp(payload: bytes, start: int) -> SpduInfo | None:
    """Parse a WSMP N-header at `start` and locate the SPDU it carries.

    The WSM length is one octet below 128, otherwise two octets with a 0x80 flag.

    Args:
        payload: Full payload.
        start: Index of the WSMP version octet.

    Returns:
        SpduInfo when the header parses and its declared length covers exactly the
        remaining bytes, otherwise None.
    """
    cursor = start
    if cursor >= len(payload) or payload[cursor] != PROTOCOL_VERSION_3:
        return None
    cursor += 2  # version, TPID

    decoded = decode_psid(payload, cursor)
    if decoded is None:
        return None
    psid, width = decoded
    cursor += width

    if cursor >= len(payload):
        return None
    first = payload[cursor]
    if first < 0x80:
        wsm_length, cursor = first, cursor + 1
    else:
        if cursor + 2 > len(payload):
            return None
        wsm_length = ((first & 0x7F) << 8) | payload[cursor + 1]
        cursor += 2

    spdu = payload[cursor : cursor + wsm_length]
    if len(spdu) < 2 or spdu[0] != PROTOCOL_VERSION_3:
        return None
    if spdu[1] not in CONTENT_CHOICES:
        return None
    # The declared length must account for exactly what remains, which rejects
    # coincidental byte patterns.
    if len(payload) - cursor != wsm_length:
        return None

    choice = CONTENT_CHOICES[spdu[1]]
    return SpduInfo(
        recognised=True,
        content_choice=choice,
        is_signed=(choice == "signedData"),
        spdu_offset=cursor,
        psid=psid,
        wsm_length=wsm_length,
        anchored=True,
    )


def locate_spdu(payload: bytes) -> SpduInfo:
    """Locate the Ieee1609Dot2Data in a payload.

    Tries, in order: a bare SPDU at offset 0; a WSMP N-header within the first
    WSMP_PREFIX_SCAN bytes or after a WSMP EtherType; an unanchored byte-pattern
    match (reported with anchored=False).

    Args:
        payload: Raw payload bytes.

    Returns:
        SpduInfo describing the SPDU, with recognised=False if none was found.
    """
    if len(payload) < 2:
        return SpduInfo(False, reason="shorter than a 1609.2 header")

    if payload[0] == PROTOCOL_VERSION_3 and payload[1] in CONTENT_CHOICES:
        choice = CONTENT_CHOICES[payload[1]]
        return SpduInfo(
            recognised=True,
            content_choice=choice,
            is_signed=(choice == "signedData"),
            spdu_offset=0,
            anchored=True,
        )

    # A vendor header can contain a stray 0x88DC, so every occurrence is tried.
    for start in range(0, min(WSMP_PREFIX_SCAN, len(payload))):
        found = parse_wsmp(payload, start)
        if found is not None:
            return found
    index = payload.find(WSMP_ETHERTYPE)
    while index >= 0:
        found = parse_wsmp(payload, index + 2)
        if found is not None:
            return found
        index = payload.find(WSMP_ETHERTYPE, index + 1)

    limit = min(FALLBACK_SCAN_LIMIT, len(payload) - 2)
    for offset in range(1, limit + 1):
        if payload[offset] == PROTOCOL_VERSION_3 and payload[offset + 1] in CONTENT_CHOICES:
            choice = CONTENT_CHOICES[payload[offset + 1]]
            return SpduInfo(
                recognised=True,
                content_choice=choice,
                is_signed=(choice == "signedData"),
                spdu_offset=offset,
                anchored=False,
                reason="unanchored byte-pattern match; not corroborated",
            )

    return SpduInfo(
        False,
        reason=(
            "no Ieee1609Dot2Data at offset 0 and no WSMP header whose declared "
            "length matches the payload"
        ),
    )


# Signature: the last field of SignedData. Only ECDSA NIST P-256 with an x-only or
# compressed rSig is supported; all of these are exactly 66 bytes:
# Signature CHOICE tag, EccP256CurvePoint CHOICE tag, 32-byte r, 32-byte s.
SIGNATURE_LENGTH = 66
ECDSA_NIST_P256_TAG = 0x80
P256_POINT_TAGS = {0x80: "x-only", 0x82: "compressed-y-0", 0x83: "compressed-y-1"}

# Prefix of a SignedData SPDU whose payload is embedded unsecured data: version 3,
# signedData, hashId sha256, SignedDataPayload with only `data`, inner version 3,
# unsecuredData. The COER length of the payload follows.
SIGNED_UNSECURED_PREFIX = bytes([PROTOCOL_VERSION_3, 0x81, 0x00, 0x40, PROTOCOL_VERSION_3, 0x80])
UNSECURED_PREFIX = bytes([PROTOCOL_VERSION_3, 0x80])


def spdu_bytes(payload: bytes, info: SpduInfo) -> bytes:
    """Return the SPDU bytes located by `locate_spdu`, bounded by the WSM length when known."""
    start = info.spdu_offset
    end = start + info.wsm_length if info.wsm_length is not None else None
    return payload[start:end]


def signature_key(spdu: bytes) -> str | None:
    """Return the signature of a signed SPDU as hex (r || s), read from its last 66 bytes.

    Returns None unless the SPDU ends in an ECDSA NIST P-256 signature with an
    x-only or compressed rSig.
    """
    if len(spdu) < SIGNATURE_LENGTH:
        return None
    if spdu[-SIGNATURE_LENGTH] != ECDSA_NIST_P256_TAG:
        return None
    if spdu[-SIGNATURE_LENGTH + 1] not in P256_POINT_TAGS:
        return None
    return spdu[-SIGNATURE_LENGTH + 2:].hex()


def _coer_length(buffer: bytes, offset: int) -> tuple[int, int] | None:
    """Decode a COER length determinant at `offset`; return (length, offset after it)."""
    if offset >= len(buffer):
        return None
    first = buffer[offset]
    if first < 0x80:
        return first, offset + 1
    width = first & 0x7F
    if width == 0 or offset + 1 + width > len(buffer):
        return None
    return int.from_bytes(buffer[offset + 1:offset + 1 + width], "big"), offset + 1 + width


def unsecured_payload(spdu: bytes) -> bytes | None:
    """Return the unsecured data carried by an SPDU (e.g. a J2735 MessageFrame).

    Supports unsecuredData SPDUs and signedData SPDUs with an embedded payload hashed
    with SHA-256 (SIGNED_UNSECURED_PREFIX); returns None for any other layout.
    """
    for prefix in (SIGNED_UNSECURED_PREFIX, UNSECURED_PREFIX):
        if spdu.startswith(prefix):
            decoded = _coer_length(spdu, len(prefix))
            if decoded is None:
                return None
            length, start = decoded
            if start + length > len(spdu):
                return None
            return spdu[start:start + length]
    return None
