from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionPolicy:
    hot_after_days: int = 0
    warm_after_days: int = 30
    cold_after_days: int = 180
    delete_after_days: int = 0

    @classmethod
    def from_env(cls) -> "RetentionPolicy":
        def _env_int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc

        return cls(
            hot_after_days=_env_int("RETENTION_HOT_DAYS", 0),
            warm_after_days=_env_int("RETENTION_WARM_DAYS", 30),
            cold_after_days=_env_int("RETENTION_COLD_DAYS", 180),
            delete_after_days=_env_int("RETENTION_DELETE_DAYS", 0),
        )

    def tier_for_age(self, age_days: float) -> str:
        if self.delete_after_days > 0 and age_days >= self.delete_after_days:
            return "delete"
        if age_days >= self.cold_after_days:
            return "cold"
        if age_days >= self.warm_after_days:
            return "warm"
        return "hot"
