"""Capability-preserving backend policy for S100 object perception.

The migration may replace an implementation only when the candidate preserves
the product capability contract. A person-only BPU detector is not an
open-vocabulary replacement.
"""
from __future__ import annotations


PRODUCT_CAPABILITIES = {
    "person_segmentation": {
        "text_open_vocabulary": False,
        "dynamic_multi_class": False,
        "recorded_video_search": False,
        "spatial_memory": False,
    },
    "open_vocabulary_search": {
        "text_open_vocabulary": True,
        "dynamic_multi_class": True,
        "recorded_video_search": False,
        "spatial_memory": False,
    },
    "recorded_video_search": {
        "text_open_vocabulary": True,
        "dynamic_multi_class": True,
        "recorded_video_search": True,
        "spatial_memory": False,
    },
    "spatial_memory": {
        "text_open_vocabulary": False,
        "dynamic_multi_class": True,
        "recorded_video_search": False,
        "spatial_memory": True,
    },
}


def missing_capabilities(product_capability, provider):
    required = PRODUCT_CAPABILITIES[product_capability]
    provider = dict(provider or {})
    return [
        name for name, required_value in required.items()
        if required_value and provider.get(name) is not True
    ]


def can_promote(product_capability, provider):
    """Return True only when the provider preserves the required feature set."""
    provider = dict(provider or {})
    if provider.get("s100_supported") is not True:
        return False
    if provider.get("api_compatible") is not True:
        return False
    if provider.get("onsite_accuracy_not_worse") is not True:
        return False
    if provider.get("realtime_ok") is not True:
        return False
    return not missing_capabilities(product_capability, provider)


def promotion_decision(product_capability, provider):
    missing = missing_capabilities(product_capability, provider)
    blockers = list(missing)
    for key in (
        "s100_supported",
        "api_compatible",
        "onsite_accuracy_not_worse",
        "realtime_ok",
    ):
        if dict(provider or {}).get(key) is not True:
            blockers.append(key)
    return {
        "product_capability": product_capability,
        "promote": not blockers,
        "blockers": blockers,
    }
