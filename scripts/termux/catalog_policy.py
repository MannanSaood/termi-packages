"""Bounded publication profiles; these are capacity limits, not package allowlists."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogPolicy:
    records: int
    repository_bytes: int
    package_bytes: int
    approval_bytes: int
    evidence_files: int


PROFILES = {
    "proof": CatalogPolicy(180, 512 * 1024**2, 96 * 1024**2, 128 * 1024, 512),
    # Includes subpackages and retained versions above the 2,225 main recipes.
    # A dedicated persistent builder/object store is required, not the APK or Pages.
    "full-catalog": CatalogPolicy(20_000, 512 * 1024**3, 2 * 1024**3, 32 * 1024**2, 100_000),
}


def policy_for(profile):
    try:
        return PROFILES[profile]
    except (KeyError, TypeError):
        raise ValueError("Unknown catalog publication profile") from None
