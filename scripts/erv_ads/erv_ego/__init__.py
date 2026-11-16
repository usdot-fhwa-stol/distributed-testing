"""carla-erv-ego: a Python-native, CARLA 0.10 ego ADS that consumes SAE J2735
BSM Part II emergency-vehicle data and yields / moves over accordingly.

Layers (each importable without CARLA except ``erv_ego.ego.agent`` and
``erv_ego.erv.driver``):

    j2735/      BSM data model, unit conversions, UPER + JSON codecs
    geo         CARLA georeference forward/inverse (matches LibCarla exactly)
    v2x/        PC5 channel model, in-process bus, UDP transport
    erv/        BSM generator from a live actor, J2945/1-style path history
    ego/        ERV tracker, situation assessment, yield/move-over policy,
                CARLA agent wrapper
"""

__version__ = "0.1.0"
