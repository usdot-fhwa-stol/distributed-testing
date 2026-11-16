"""C-V2X PC5 (sidelink, mode 4 / SPS) channel model.

Deliberately simple but shaped like field data:

* Packet error rate vs range is a logistic curve with a 50%-PER distance
  (d50) that drops sharply when the link is non-line-of-sight. Defaults
  (450 m LOS / 150 m NLOS) sit inside the range commonly reported for
  urban/suburban PC5 BSM tests at 20 dBm; tune them to your Ettifos /
  Commsignia bench and GoMentum/RFS drive data.
* A residual short-range loss floor stands in for half-duplex misses and
  resource collisions.
* Latency is uniform over the SPS resource-selection window (default
  3-50 ms), applied in simulation time so runs stay deterministic.
* LOS is decided by an injected function; in CARLA that is a raycast against
  buildings/terrain/vegetation (see carla_compat.make_raycast_los).

Apply this only to simulated links. Messages that already came over real RF
(an OBU forwarding to UDP) should bypass it (``enabled: false``).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

Vec3 = Tuple[float, float, float]


@dataclass
class ChannelConfig:
    enabled: bool = True
    d50_los_m: float = 450.0
    d50_nlos_m: float = 150.0
    slope_m: float = 50.0
    floor_per: float = 0.005
    latency_min_ms: float = 3.0
    latency_max_ms: float = 50.0
    raycast_los: bool = True
    seed: Optional[int] = 7

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "ChannelConfig":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ChannelStats:
    offered: int = 0
    delivered: int = 0
    dropped_range: int = 0
    nlos_samples: int = 0
    latency_ms_sum: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        pdr = self.delivered / self.offered if self.offered else None
        return {"offered": self.offered, "delivered": self.delivered, "dropped": self.dropped_range,
                "pdr": pdr, "nlos_fraction": (self.nlos_samples / self.offered) if self.offered else None,
                "mean_latency_ms": (self.latency_ms_sum / self.delivered) if self.delivered else None}


class Pc5Channel:
    def __init__(self, cfg: ChannelConfig, los_fn: Optional[Callable[[Vec3, Vec3], bool]] = None):
        self.cfg = cfg
        self.los_fn = los_fn if cfg.raycast_los else None
        self.rng = random.Random(cfg.seed)
        self.stats = ChannelStats()

    def per(self, distance_m: float, los: bool) -> float:
        d50 = self.cfg.d50_los_m if los else self.cfg.d50_nlos_m
        z = (distance_m - d50) / max(self.cfg.slope_m, 1e-3)
        z = max(min(z, 60.0), -60.0)
        logistic = 1.0 / (1.0 + math.exp(-z))
        return self.cfg.floor_per + (1.0 - self.cfg.floor_per) * logistic

    def sample(self, tx: Vec3, rx: Vec3) -> Tuple[bool, float, Dict]:
        """Return (delivered, latency_s, info)."""
        distance = math.dist(tx, rx)
        if not self.cfg.enabled:
            return True, 0.0, {"distance_m": distance, "los": None, "per": 0.0}
        los = True
        if self.los_fn is not None:
            try:
                los = bool(self.los_fn(tx, rx))
            except Exception:
                los = True
        p = self.per(distance, los)
        self.stats.offered += 1
        if not los:
            self.stats.nlos_samples += 1
        if self.rng.random() < p:
            self.stats.dropped_range += 1
            return False, 0.0, {"distance_m": distance, "los": los, "per": p}
        lat_ms = self.rng.uniform(self.cfg.latency_min_ms, self.cfg.latency_max_ms)
        self.stats.delivered += 1
        self.stats.latency_ms_sum += lat_ms
        return True, lat_ms / 1000.0, {"distance_m": distance, "los": los, "per": p, "latency_ms": lat_ms}
