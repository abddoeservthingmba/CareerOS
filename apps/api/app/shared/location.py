"""Location - `FOUND-03`.

`01-foundations.md` §3: "`Location{raw, city, region, country: ISO3166-1
alpha-2, remote_mode}`. `country` is the only field guaranteed non-null after
normalization. `remote_mode ∈ {onsite, hybrid, remote, unknown}`."

The resolver that *produces* a `Location` from a listing's free text is
`JOB-04` (`07-ingestion-and-jobs.md` §4) and is phase P3. This is only the
shape, plus the one invariant every producer must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.enums import RemoteMode


@dataclass(frozen=True, slots=True)
class Location:
    """A place, as supplied and as resolved.

    `raw` is what the source said and is never overwritten - the UI shows it,
    and a normalizer bug is diagnosable only if the input survives.
    """

    raw: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_mode: RemoteMode = RemoteMode.UNKNOWN

    def __post_init__(self) -> None:
        if self.country is not None:
            country = self.country.upper()
            if len(country) != 2 or not country.isalpha():
                raise ValueError(
                    f"country must be an ISO 3166-1 alpha-2 code, got {self.country!r}"
                )
            object.__setattr__(self, "country", country)
        object.__setattr__(self, "remote_mode", RemoteMode(self.remote_mode))

    @property
    def resolved(self) -> bool:
        """`JOB-04`: an unresolved location is stored but never scores points."""
        return self.country is not None

    @property
    def is_remote(self) -> bool:
        return self.remote_mode is RemoteMode.REMOTE

    def __str__(self) -> str:
        parts = [p for p in (self.city, self.region, self.country) if p]
        return ", ".join(parts) if parts else self.raw
