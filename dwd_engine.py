"""
Shared engine for pulling any one of DWD's "daily" station networks
(config.NETWORKS) down to a local Parquet file.

Three stages, same shape as most scrapers in this portfolio:

  1. list_dir()        - parse a DWD directory-listing page into (name, url)
                          pairs. Used both to find the station description
                          file and to enumerate every station's zip in
                          historical/ and recent/. Nothing is hardcoded by
                          filename - the server is asked what's actually
                          there, so a naming quirk on one network can't break
                          another.
  2. mirror_network()  - download every zip (+ the station list) for one
                          network into raw/<network>/. historical/ zips are
                          frozen once a calendar year closes, so they're
                          skipped once already on disk. recent/ zips cover a
                          rolling ~500-day window and are re-downloaded every
                          run so today's reading actually shows up.
  3. build_network()   - unzip in memory, keep only the "produkt_*" member of
                          each archive, parse it, concatenate every station,
                          and join in station name/lat/lon/elevation from the
                          station list. Writes data/<network>.parquet.

Nothing here is network-specific beyond the folder name in config.NETWORKS, so
adding a fifth DWD network later is a one-line change to config.py.
"""
from __future__ import annotations

import re
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

import config

# Plain Apache/nginx-style autoindex link, e.g. href="tageswerte_KL_00003...".
# Skips "../" (parent-dir link) and "?C=N;O=D"-style sort-column links, which
# is all the "site chrome" a DWD listing page has - much simpler than scraping
# a normal website.
HREF_RE = re.compile(r'href="([^"?/][^"?]*)"')

S = requests.Session()
S.headers["User-Agent"] = (
    "dwd-climate-data-center/1.0 (personal learning project; github.com/vulevu228)"
)


def _get(url: str) -> requests.Response:
    """GET with a few retries on connection errors / 5xx.

    Same pattern used across this portfolio's fetch scripts, so a flaky
    moment on DWD's server doesn't kill a multi-hour mirror run. A 4xx (e.g.
    404 for a network that doesn't publish recent/) is a real answer and is
    raised immediately, not retried.
    """
    for attempt in range(config.RETRIES):
        try:
            r = S.get(url, timeout=config.TIMEOUT)
            if r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} {url}")
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if attempt == config.RETRIES - 1:
                raise
            time.sleep(2 * (attempt + 1))   # 2s, 4s, ... simple linear back-off
    raise RuntimeError("unreachable")


def list_dir(url: str) -> list[tuple[str, str]]:
    """Return (filename, absolute_url) for every entry in a DWD autoindex page."""
    base = url if url.endswith("/") else url + "/"
    return [(href, base + href) for href in HREF_RE.findall(_get(base).text)]


def mirror_network(name: str) -> None:
    """Download every file for one network (config.NETWORKS[name]) into raw/<name>/.

    Unlike PEGELONLINE, DWD's "<CODE>_..._Stationen.txt" station list is not
    published once at the network root - it's duplicated inside *both*
    historical/ and recent/ (identical content either way), so it's picked up
    while walking those two folders below rather than fetched separately.
    """
    meta = config.NETWORKS[name]
    root = config.DAILY_ROOT + meta["folder"] + "/"
    local_root = config.RAW / name
    local_root.mkdir(parents=True, exist_ok=True)

    station_list_saved = False
    # --- data zips: historical/ is frozen (skip once on disk), recent/ is a
    #     rolling window and must be re-pulled in full every run ------------
    for period in ("historical", "recent"):
        period_url = root + period + "/"
        try:
            entries = list_dir(period_url)
        except requests.HTTPError:
            continue   # not every network publishes both periods
        period_dir = local_root / period
        period_dir.mkdir(exist_ok=True)

        if not station_list_saved:
            for fname, url in entries:
                if fname.lower().endswith("stationen.txt"):
                    (local_root / fname).write_bytes(_get(url).content)
                    print(f"[{name}] station list -> {fname}")
                    station_list_saved = True
                    break

        zips = [(f, u) for f, u in entries if f.endswith(".zip")]
        new = present = failed = 0
        for fname, url in zips:
            dest = period_dir / fname
            if period == "historical" and dest.exists():
                present += 1
                continue
            try:
                dest.write_bytes(_get(url).content)
                new += 1
            except requests.HTTPError:
                failed += 1
            time.sleep(config.PAUSE)
        print(f"[{name}] {period}: {len(zips)} files "
              f"({new} new, {present} already present, {failed} failed)")


def _parse_station_list(path: Path) -> pd.DataFrame:
    """Parse a DWD '*_Stationen.txt' station table.

    The header line is underlined with a row of dashes that LOOKS like it
    marks fixed-width column widths - it doesn't. Checked against the live
    files for all four networks in config.NETWORKS: values are simply
    whitespace-separated, not padded to those widths, so pandas.read_fwf with
    dash-derived colspecs silently misaligns every column after the first.
    Splitting on whitespace is the actually-correct parse: the first six
    fields (id, two dates, elevation, lat, lon) are plain numbers with no
    internal spaces, and the last two (Bundesland, Abgabe) are always a
    single word each. Everything left in the middle is the station name -
    which can itself contain spaces (e.g. "Donaueschingen (Landeplatz)") - so
    splitting 6 tokens off the front and 2 off the back is what's needed
    rather than a plain str.split().
    """
    rows = []
    with open(path, encoding="latin-1") as f:
        header = f.readline().split()
        f.readline()   # dashed underline - decorative only, see docstring
        for line in f:
            if not line.strip():
                continue
            parts = line.split(maxsplit=6)
            if len(parts) < 7:
                continue   # malformed/short line - skip rather than crash a mirror run
            *head, rest = parts
            try:
                name, state, abgabe = rest.rsplit(maxsplit=2)
            except ValueError:
                continue
            rows.append((*head, name.strip(), state, abgabe))

    df = pd.DataFrame(rows, columns=header)
    df = df.rename(columns={
        "Stations_id": "station_id", "Stationshoehe": "elevation_m",
        "geoBreite": "lat", "geoLaenge": "lon", "Stationsname": "station_name",
        "Bundesland": "state", "von_datum": "date_from", "bis_datum": "date_to",
    })
    df["station_id"] = df["station_id"].astype(str).str.zfill(5)
    for col in ("elevation_m", "lat", "lon"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("date_from", "date_to"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")
    return df


def _read_produkt_file(zf: zipfile.ZipFile) -> pd.DataFrame | None:
    """Pull the one 'produkt_*' member out of a station zip and parse it.

    Each zip also carries Metadaten_*.txt files (sensor history, station
    moves, QC notes) which describe the measurement, not the measurement
    itself - out of scope for a portfolio dashboard, so they're skipped.
    """
    produkt_names = [n for n in zf.namelist() if n.lower().startswith("produkt_")]
    if not produkt_names:
        return None
    with zf.open(produkt_names[0]) as f:
        df = pd.read_csv(f, sep=";", encoding="latin-1")
    df.columns = df.columns.str.strip()
    df = df.rename(columns={"STATIONS_ID": "station_id", "MESS_DATUM": "date"})
    df["station_id"] = df["station_id"].astype(str).str.zfill(5)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")

    # every numeric column uses -999 (config.MISSING) for "not measured";
    # QN_3/QN_4 are per-reading quality-control codes, not values - dropped
    # to keep the model lean, along with the trailing "eor" end-of-record marker
    drop_cols = [c for c in ("eor", "QN_3", "QN_4") if c in df.columns]
    value_cols = [c for c in df.columns if c not in ("station_id", "date", *drop_cols)]
    for c in value_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").replace(config.MISSING, pd.NA)
    return df.drop(columns=drop_cols)


def build_network(name: str) -> pd.DataFrame:
    """Parse every mirrored zip for one network and write data/<name>.parquet.

    Runs entirely against raw/ - no network access - so it can be re-run for
    free after tweaking the parsing logic, without re-downloading anything.
    """
    local_root = config.RAW / name
    desc_files = list(local_root.glob("*Stationen.txt"))
    stations = _parse_station_list(desc_files[0]) if desc_files else pd.DataFrame()

    # sorted() puts historical/*.zip before recent/*.zip (h < r alphabetically),
    # which matters below: where the two periods overlap, we want recent/'s
    # row to win, and it does because it's concatenated later.
    zips = sorted(local_root.glob("*/*.zip"))
    frames = []
    for i, zpath in enumerate(zips, 1):
        try:
            with zipfile.ZipFile(zpath) as zf:
                df = _read_produkt_file(zf)
            if df is not None and not df.empty:
                frames.append(df)
        except (zipfile.BadZipFile, pd.errors.ParserError) as e:
            print(f"  ! skipped {zpath.name}: {e}")
        if i % 200 == 0:
            print(f"[{name}] parsed {i}/{len(zips)} zips")

    if not frames:
        raise SystemExit(f"[{name}] no data parsed - did mirror_network('{name}') run first?")

    daily = pd.concat(frames, ignore_index=True)
    # recent/ overlaps historical/ by design (the rolling window laps the last
    # closed year) - keep one row per station/day, preferring the later one
    # in the concatenation, i.e. the recent/ reading (see sort comment above).
    daily = daily.sort_values(["station_id", "date"]).drop_duplicates(
        subset=["station_id", "date"], keep="last"
    )

    if not stations.empty:
        keep = [c for c in ("station_id", "station_name", "state", "lat", "lon", "elevation_m")
                if c in stations.columns]
        daily = daily.merge(stations[keep], on="station_id", how="left")

    out = config.DATA / f"{name}.parquet"
    daily.to_parquet(out, index=False)
    print(f"[{name}] {len(daily):,} rows, {daily['station_id'].nunique()} stations -> {out}")
    return daily
