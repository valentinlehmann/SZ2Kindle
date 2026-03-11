"""Delivery strategies for SZ2Kindle."""

from __future__ import annotations

import configparser
import logging
from abc import ABC, abstractmethod
from pathlib import Path

log = logging.getLogger("sz2kindle")

STRATEGY_REGISTRY: dict[str, type[DeliveryStrategy]] = {}


class DeliveryStrategy(ABC):
    """Base class for epub delivery strategies."""

    @abstractmethod
    def already_delivered(self, filename: str) -> bool:
        """Check whether the given epub has already been delivered."""

    @abstractmethod
    def deliver(self, epub_path: Path) -> None:
        """Deliver the epub file to its destination."""


def register(name: str):
    """Decorator to register a strategy class under a given name."""
    def decorator(cls: type[DeliveryStrategy]) -> type[DeliveryStrategy]:
        STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator


def get_strategy(config: configparser.ConfigParser) -> DeliveryStrategy:
    """Instantiate and return the configured delivery strategy."""
    # Import strategy modules to trigger registration.
    from strategies import email, webdav  # noqa: F401

    name = config.get("general", "strategy", fallback="email")
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {', '.join(STRATEGY_REGISTRY)}"
        )
    log.info("Using delivery strategy: %s", name)
    return cls(config)
