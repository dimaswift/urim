"""Download source data into data/sources/ and pin it in sources.lock.json.

GitHub sources are fetched from a fixed commit, so their URLs are immutable. The lockfile
records each file's SHA-256: a later fetch that finds different bytes fails instead of silently
building from changed data. `refresh=True` re-downloads and re-pins.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx

STEPBIBLE_COMMIT = "be4191f0082aeedddb0eff0c02c966292b2bd641"
SCROLLMAPPER_COMMIT = "59b18c5af5845728c275d5b7178ad0d024172b1f"
OPENBIBLE_COMMIT = "7eb18a5ee62f27b9b93bd6689ea272d76dd23b8f"
NATURAL_EARTH_COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"

USER_AGENT = "urim-ingest/0.1 (+https://github.com/; research use)"


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    path: str  # relative to the sources directory
    attribution: str


def _github(repo: str, commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{quote(path)}"


def _stepbible(key: str, repo_path: str) -> Source:
    return Source(
        key=key,
        url=_github("STEPBible/STEPBible-Data", STEPBIBLE_COMMIT, repo_path),
        path=f"stepbible/{key.removeprefix('stepbible/')}.txt",
        attribution=f"STEPBible.org, {repo_path.rsplit('/', 1)[-1].split(' - ')[0]}, CC BY 4.0",
    )


TAHOT_FILES = {
    # TAHOT is split into four files by book range; book codes map to the file that holds them.
    "Gen-Deu": ("GEN", "EXOD", "LEV", "NUM", "DEUT"),
    "Jos-Est": (
        "JOSH",
        "JUDG",
        "RUTH",
        "1SAM",
        "2SAM",
        "1KGS",
        "2KGS",
        "1CHR",
        "2CHR",
        "EZRA",
        "NEH",
        "ESTH",
    ),
    "Job-Sng": ("JOB", "PS", "PROV", "ECCL", "SONG"),
    "Isa-Mal": (
        "ISA",
        "JER",
        "LAM",
        "EZEK",
        "DAN",
        "HOS",
        "JOEL",
        "AMOS",
        "OBAD",
        "JONAH",
        "MIC",
        "NAH",
        "HAB",
        "ZEPH",
        "HAG",
        "ZECH",
        "MAL",
    ),
}

SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        *(
            _stepbible(
                f"stepbible/tahot_{part.lower().replace('-', '_')}",
                f"Translators Amalgamated OT+NT/TAHOT {part} - Translators Amalgamated Hebrew OT"
                " - STEPBible.org CC BY.txt",
            )
            for part in TAHOT_FILES
        ),
        _stepbible(
            "stepbible/tvtms",
            "Versification/TVTMS - Translators Versification Traditions with Methodology for "
            "Standardisation for Eng+Heb+Lat+Grk+Others - STEPBible.org CC BY.txt",
        ),
        _stepbible(
            "stepbible/tipnr",
            "Proper Nouns/TIPNR - Translators Individualised Proper Names with all References"
            " - STEPBible.org CC BY.txt",
        ),
        *(
            Source(
                key=f"scrollmapper/{name}",
                url=_github(
                    "scrollmapper/bible_databases", SCROLLMAPPER_COMMIT, f"formats/json/{name}.json"
                ),
                path=f"scrollmapper/{name}.json",
                attribution=f"{name} via scrollmapper/bible_databases (public domain text)",
            )
            for name in ("KJV", "YLT", "ASV", "BBE", "Webster", "RusSynodal")
        ),
        *(
            Source(
                key=f"openbible/{name}",
                url=_github(
                    "openbibleinfo/Bible-Geocoding-Data", OPENBIBLE_COMMIT, f"data/{name}.jsonl"
                ),
                path=f"openbible/{name}.jsonl",
                attribution="OpenBible.info Bible Geocoding Data, CC BY 4.0",
            )
            for name in ("ancient",)
        ),
        *(
            Source(
                key=f"naturalearth/{name}",
                url=_github(
                    "nvkelso/natural-earth-vector", NATURAL_EARTH_COMMIT, f"geojson/{name}.geojson"
                ),
                path=f"naturalearth/{name}.geojson",
                attribution="Natural Earth (public domain)",
            )
            for name in (
                "ne_10m_land",
                "ne_10m_lakes",
                "ne_10m_rivers_lake_centerlines",
                "ne_10m_geography_regions_polys",
            )
        ),
    ]
}


class SourceChanged(RuntimeError):
    pass


class Fetcher:
    """Fetches and verifies sources against a lockfile."""

    def __init__(
        self,
        sources_dir: Path,
        lockfile: Path,
        *,
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
    ):
        self.sources_dir = Path(sources_dir)
        self.lockfile = Path(lockfile)
        self.refresh = refresh
        self.lock: dict[str, dict] = (
            json.loads(self.lockfile.read_text()) if self.lockfile.exists() else {}
        )
        self._transport = transport
        self._client: httpx.Client | None = None

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc) -> None:
        if self._client is not None:
            self._client.close()
        self.save()

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=120,
                follow_redirects=True,
                transport=self._transport,
            )
        return self._client

    def save(self) -> None:
        self.lockfile.write_text(json.dumps(dict(sorted(self.lock.items())), indent=2) + "\n")

    def get(self, source: Source) -> Path:
        return self.get_url(source.key, source.url, source.path)

    def get_url(self, key: str, url: str, rel_path: str) -> Path:
        path = self.sources_dir / rel_path
        pinned = self.lock.get(key)
        if path.exists() and not self.refresh:
            digest = _sha256(path)
            if pinned and pinned["sha256"] != digest:
                raise SourceChanged(f"{path} does not match sources.lock.json; refresh to re-pin")
        else:
            digest = self._download(url, path)
            if pinned and pinned["sha256"] != digest and not self.refresh:
                path.unlink()
                raise SourceChanged(f"{url} changed upstream; refresh to re-pin")
        if not pinned or pinned["sha256"] != digest or pinned["url"] != url:
            self.lock[key] = {
                "url": url,
                "path": rel_path,
                "sha256": digest,
                "bytes": path.stat().st_size,
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        return path

    def _download(self, url: str, path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        h = hashlib.sha256()
        with self.client.stream("GET", url) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
                    h.update(chunk)
        tmp.replace(path)
        return h.hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
