"""Assemble pipeline components from a config dict (shared by all scripts)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from .clock import Clock, make_clock
from .ego.policy import ErvPolicy, PolicyConfig
from .ego.receiver import V2xReceiver
from .ego.tracker import ErvTracker
from .erv.bsm_generator import BsmGenerator, profile_from_config
from .geo import CarlaGeoRef
from .j2735.codec import Codec, make_codec
from .v2x.channel import ChannelConfig, Pc5Channel
from .v2x.transport import UdpReceiver, UdpSender

log = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def codec_from_cfg(cfg: Dict[str, Any]) -> Codec:
    v2x = cfg["v2x"]
    asn1_dir = v2x.get("asn1_dir", "asn1")
    if not os.path.isabs(asn1_dir):
        asn1_dir = os.path.join(REPO_ROOT, asn1_dir)
    return make_codec(v2x.get("codec", "auto"), asn1_dir)


def clock_from_cfg(cfg: Dict[str, Any]) -> Clock:
    c = cfg.get("clock", {})
    return make_clock(c.get("kind", "sim"), float(c.get("sim_epoch_utc", 1767225600)))


def channel_from_cfg(cfg: Dict[str, Any], world=None) -> Optional[Pc5Channel]:
    ch_cfg = ChannelConfig.from_dict(cfg["v2x"].get("channel"))
    if not ch_cfg.enabled:
        return None
    los = None
    if world is not None and ch_cfg.raycast_los:
        from .carla_compat import make_raycast_los
        los = make_raycast_los(world)
    return Pc5Channel(ch_cfg, los)


def tracker_from_cfg(cfg: Dict[str, Any], clock: Clock, evidence=None) -> ErvTracker:
    t = cfg.get("tracker", {})
    return ErvTracker(clock, max_age_ms=int(t.get("max_age_ms", 1000)),
                      future_tolerance_ms=int(t.get("future_tolerance_ms", 200)),
                      stale_s=float(t.get("stale_s", 1.0)), drop_s=float(t.get("drop_s", 3.0)),
                      gate_m=float(t.get("gate_m", 10.0)), gate_heading_deg=float(t.get("gate_heading_deg", 30.0)),
                      evidence=evidence)


def policy_from_cfg(cfg: Dict[str, Any], evidence=None) -> ErvPolicy:
    return ErvPolicy(PolicyConfig.from_dict(cfg.get("policy")), evidence)


def erv_generator_from_cfg(cfg: Dict[str, Any], georef: CarlaGeoRef, clock: Clock) -> BsmGenerator:
    e = cfg["erv"]
    profile = profile_from_config(e.get("bsm_profile", "stol_sample"), e.get("profile_overrides"))
    return BsmGenerator(georef, clock, profile, kind=e.get("kind", "firetruck"),
                        id_rotation_s=float(e.get("temp_id_rotation_s", 0)),
                        gnss_sigma_m=float(e.get("gnss_sigma_m", 0.0)), gnss_tau_s=float(e.get("gnss_tau_s", 30)),
                        seed=e.get("seed"))


def ego_generator_from_cfg(cfg: Dict[str, Any], georef: CarlaGeoRef, clock: Clock) -> BsmGenerator:
    return BsmGenerator(georef, clock, profile_from_config("basic"), kind="passenger",
                        id_rotation_s=300.0, gnss_sigma_m=0.8, seed=(cfg["erv"].get("seed") or 0) + 101)


def udp_endpoints(cfg: Dict[str, Any]):
    u = cfg["v2x"]["udp"]
    erv_tx = UdpSender(u["erv_tx_host"], u["erv_tx_port"])
    ego_rx = UdpReceiver(u["ego_rx_bind"], u["ego_rx_port"], multicast_group=u.get("multicast_group"))
    ego_tx = UdpSender(u["ego_tx_host"], u["ego_tx_port"])
    return erv_tx, ego_rx, ego_tx


def receiver_from_cfg(cfg, endpoints: List[Any], codec: Codec, georef: CarlaGeoRef, world=None,
                      evidence=None) -> V2xReceiver:
    return V2xReceiver(endpoints, codec, georef, channel_from_cfg(cfg, world), evidence)
