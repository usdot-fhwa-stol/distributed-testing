"""YAML config loading with deep-merge over the packaged defaults."""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, Optional

import yaml

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "default.yaml")


def deep_merge(base: Dict[str, Any], over: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    with open(DEFAULT_PATH) as f:
        cfg = yaml.safe_load(f)
    if path and os.path.abspath(path) != os.path.abspath(DEFAULT_PATH):
        with open(path) as f:
            cfg = deep_merge(cfg, yaml.safe_load(f) or {})
    return cfg


def set_dotted(cfg: Dict[str, Any], dotted: str, value: str) -> None:
    """Apply a CLI override like ``policy.yield_trigger_ttr_s=10``."""
    keys = dotted.split(".")
    cur = cfg
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = yaml.safe_load(value)
