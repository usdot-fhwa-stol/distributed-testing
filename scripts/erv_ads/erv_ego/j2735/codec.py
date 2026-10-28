"""J2735 codecs.

``Asn1Codec`` encodes/decodes real UPER MessageFrames using the SAE J2735
ASN.1 you supply (licensed from SAE; drop the module files into ``asn1/``).
asn1tools represents J2735 open types (MessageFrame.value, partII-Value) as
already-encoded octets, so this codec works in two stages:

    MessageFrame -> BasicSafetyMessage -> each PartII value by partII-Id

``JsonCodec`` carries the same value structure as JSON. It exists so the
whole pipeline runs before the ASN.1 is in place, and for systems that
forward already-decoded messages. It is NOT a J2735 wire format.

``locate`` logic: OBU UDP forwarders and V2X Hub sometimes prepend headers
(WSMP, IEEE 1609.2, vendor framing). The UPER decoder therefore scans for a
plausible MessageFrame start (0x00 followed by a known DSRCmsgID byte, e.g.
``00 14`` for a BSM) when decoding at offset 0 fails.
"""

from __future__ import annotations

import abc
import glob
import json
import logging
import os
import string
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from . import constants as C
from .bsm import Bsm

log = logging.getLogger(__name__)

KNOWN_MSG_IDS = {C.MSG_ID_MAP, C.MSG_ID_SPAT, C.MSG_ID_BSM, C.MSG_ID_EVA, C.MSG_ID_RSA,
                 C.MSG_ID_SRM, C.MSG_ID_SSM, C.MSG_ID_TIM, C.MSG_ID_PSM}

_HEX = set(string.hexdigits.encode()) | set(b" \r\n\t:")


@dataclass
class DecodedMessage:
    message_id: int
    bsm: Optional[Bsm]
    raw: Any
    codec: str
    offset: int = 0


def normalize_payload(payload: bytes) -> bytes:
    """Accept raw octets or ASCII hex (with optional spaces/colons/newlines)."""
    if payload and all(b in _HEX for b in payload):
        text = payload.decode().replace(" ", "").replace(":", "").strip()
        if text and len(text) % 2 == 0:
            try:
                return bytes.fromhex(text)
            except ValueError:
                pass
    return payload


class Codec(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def encode_bsm(self, bsm: Bsm) -> bytes: ...

    @abc.abstractmethod
    def decode(self, payload: bytes) -> Optional[DecodedMessage]: ...


# ----------------------------------------------------------------------------
# UPER via asn1tools + user-supplied J2735 ASN.1
# ----------------------------------------------------------------------------

class Asn1Codec(Codec):
    name = "uper"

    FRAME_TYPE = "MessageFrame"
    BSM_TYPE = "BasicSafetyMessage"

    def __init__(self, asn1_files: List[str], cache_dir: Optional[str] = None,
                 scan_limit: int = 128, check_constraints: bool = True):
        import asn1tools  # imported lazily so the JSON path has no dependency

        if not asn1_files:
            raise FileNotFoundError("no J2735 ASN.1 files given")
        self._spec = asn1tools.compile_files(asn1_files, "uper", cache_dir=cache_dir)
        missing = [t for t in (self.FRAME_TYPE, self.BSM_TYPE, *C.PARTII_TYPE_NAMES.values())
                   if t not in self._spec.types]
        if missing:
            raise ValueError(f"J2735 ASN.1 is missing types: {missing}")
        self._scan_limit = scan_limit
        # Range-check every encode so an out-of-range field fails here, not at the receiver.
        self.check_constraints = check_constraints
        log.info("UPER codec ready (%d ASN.1 modules)", len(asn1_files))

    @classmethod
    def from_dir(cls, asn1_dir: str, **kw) -> "Asn1Codec":
        files = sorted(glob.glob(os.path.join(asn1_dir, "*.asn")) +
                       glob.glob(os.path.join(asn1_dir, "*.asn1")))
        cache = os.path.join(asn1_dir, ".cache")
        return cls(files, cache_dir=cache, **kw)

    # -- low-level helpers (also used by tests with a toy schema) ---------------
    def _encode_open(self, type_name: str, value: Any) -> bytes:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        return self._spec.encode(type_name, value, check_constraints=self.check_constraints)

    def _decode_open(self, type_name: str, value: Any) -> Any:
        if isinstance(value, (bytes, bytearray)):
            return self._spec.decode(type_name, bytes(value))
        return value

    def encode_frame(self, message_id: int, inner_type: str, inner_value: Any) -> bytes:
        inner = self._encode_open(inner_type, inner_value)
        try:
            return self._spec.encode(self.FRAME_TYPE, {"messageId": message_id, "value": inner},
                                     check_constraints=self.check_constraints)
        except TypeError:
            # ASN.1 compiled with a resolved (non-open) value type
            return self._spec.encode(self.FRAME_TYPE, {"messageId": message_id, "value": inner_value},
                                     check_constraints=self.check_constraints)

    # -- BSM --------------------------------------------------------------------
    def encode_bsm(self, bsm: Bsm) -> bytes:
        value = bsm.to_asn1_dict()
        for item in value.get("partII", []):
            pid = item["partII-Id"]
            if pid in C.PARTII_TYPE_NAMES:
                item["partII-Value"] = self._encode_open(C.PARTII_TYPE_NAMES[pid], item["partII-Value"])
        return self.encode_frame(C.MSG_ID_BSM, self.BSM_TYPE, value)

    def _try_decode_at(self, payload: bytes, offset: int) -> Optional[DecodedMessage]:
        try:
            frame = self._spec.decode(self.FRAME_TYPE, payload[offset:])
        except Exception:
            return None
        mid = frame.get("messageId")
        if mid not in KNOWN_MSG_IDS:
            return None
        if mid != C.MSG_ID_BSM:
            return DecodedMessage(mid, None, frame, self.name, offset)
        try:
            bsm_value = self._decode_open(self.BSM_TYPE, frame["value"])
            for item in bsm_value.get("partII", []) or []:
                pid = item["partII-Id"]
                if pid in C.PARTII_TYPE_NAMES:
                    item["partII-Value"] = self._decode_open(C.PARTII_TYPE_NAMES[pid], item["partII-Value"])
            return DecodedMessage(mid, Bsm.from_asn1_dict(bsm_value), bsm_value, self.name, offset)
        except Exception as exc:  # malformed inner content
            log.debug("BSM inner decode failed at offset %d: %s", offset, exc)
            return None

    def _candidate_offsets(self, payload: bytes) -> Iterable[int]:
        yield 0
        limit = min(len(payload) - 2, self._scan_limit)
        for i in range(1, limit + 1):
            if payload[i] == 0x00 and payload[i + 1] in KNOWN_MSG_IDS:
                yield i

    def decode(self, payload: bytes) -> Optional[DecodedMessage]:
        payload = normalize_payload(payload)
        for off in self._candidate_offsets(payload):
            msg = self._try_decode_at(payload, off)
            if msg is not None:
                return msg
        return None


# ----------------------------------------------------------------------------
# JSON transport of the same value structure
# ----------------------------------------------------------------------------

_BYTES_KEYS = {"id"}  # OCTET STRING fields in the BSM tree


def _to_json(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _to_json(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_to_json(x) for x in v]
    if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], (bytes, bytearray)):
        return {"value": bytes(v[0]).hex(), "length": v[1]}       # BIT STRING
    if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str):
        return {v[0]: _to_json(v[1])}                             # CHOICE
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return v


def _from_json(v: Any, key: Optional[str] = None) -> Any:
    if isinstance(v, dict):
        if set(v) == {"value", "length"} and isinstance(v["value"], str):
            return bytes.fromhex(v["value"]), int(v["length"])
        return {k: _from_json(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_from_json(x, key) for x in v]
    if key in _BYTES_KEYS and isinstance(v, str):
        return bytes.fromhex(v)
    return v


class JsonCodec(Codec):
    name = "json"

    def encode_bsm(self, bsm: Bsm) -> bytes:
        frame = {"messageId": C.MSG_ID_BSM, "value": _to_json(bsm.to_asn1_dict())}
        return json.dumps(frame, separators=(",", ":")).encode()

    def decode(self, payload: bytes) -> Optional[DecodedMessage]:
        text = payload.lstrip()
        if not text.startswith(b"{"):
            return None
        try:
            obj = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            return None
        if "coreData" in obj:                       # bare BSM
            obj = {"messageId": C.MSG_ID_BSM, "value": obj}
        mid = obj.get("messageId")
        if mid != C.MSG_ID_BSM:
            return DecodedMessage(mid, None, obj, self.name)
        try:
            value = _from_json(obj["value"])
            return DecodedMessage(mid, Bsm.from_asn1_dict(value), value, self.name)
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("JSON BSM decode failed: %s", exc)
            return None


class MultiCodec(Codec):
    """Encode with the first codec, decode with whichever recognises the payload."""

    def __init__(self, codecs: List[Codec]):
        if not codecs:
            raise ValueError("MultiCodec needs at least one codec")
        self.codecs = codecs
        self.name = "+".join(c.name for c in codecs)

    def encode_bsm(self, bsm: Bsm) -> bytes:
        return self.codecs[0].encode_bsm(bsm)

    def decode(self, payload: bytes) -> Optional[DecodedMessage]:
        json_first = payload.lstrip().startswith(b"{")
        order = sorted(self.codecs, key=lambda c: 0 if (c.name == "json") == json_first else 1)
        for c in order:
            msg = c.decode(payload)
            if msg is not None:
                return msg
        return None


def make_codec(mode: str = "auto", asn1_dir: str = "asn1") -> Codec:
    """Build the codec stack.

    auto -> UPER if J2735 ASN.1 is present (decode also accepts JSON), else JSON
    uper -> UPER required
    json -> JSON only
    """
    mode = (mode or "auto").lower()
    if mode == "json":
        return JsonCodec()
    try:
        uper = Asn1Codec.from_dir(asn1_dir)
    except (ImportError, FileNotFoundError, ValueError) as exc:
        if mode == "uper":
            raise
        log.warning("UPER codec unavailable (%s); falling back to JSON transport. "
                    "Put the SAE J2735 ASN.1 modules in %s/ for real UPER.", exc, asn1_dir)
        return JsonCodec()
    return MultiCodec([uper, JsonCodec()])
