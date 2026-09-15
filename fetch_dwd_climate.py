"""
CLI entry point for the DWD Climate Data Center pipeline. Wires dwd_engine.py
to the four networks listed in config.NETWORKS.

Two stages, same as this portfolio's other scrapers:
  mirror  - download every station zip for the requested network(s) into raw/
  build   - parse raw/ into one tidy data/<network>.parquet per network

Usage:
  python fetch_dwd_climate.py                    # mirror + build, all 4 networks
  python fetch_dwd_climate.py --networks kl       # just general climate (smallest, ~1,200 stations)
  python fetch_dwd_climate.py mirror              # download only (e.g. before a flight)
  python fetch_dwd_climate.py build               # rebuild Parquet only, no network access
  python fetch_dwd_climate.py mirror --networks kl,water_equiv

First run downloads the FULL historical archive for every station in the
chosen network(s) - for "kl" alone that's ~1,200 stations x up to ~140 years
of daily data, several GB and well over an hour end to end. Every run after
that only re-pulls recent/ (small) plus any *new* historical zip DWD has
published since the last calendar year closed, so it finishes in minutes.
That's why this is meant to run once a day via run_daily.bat, not once.
"""
from __future__ import annotations

import argparse

import config
import dwd_engine as engine


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mirror + build DWD Climate Data Center networks.")
    p.add_argument("stage", nargs="?", choices=["mirror", "build"], default=None,
                    help="run only one stage; default runs both, network by network")
    p.add_argument("--networks", default=",".join(config.NETWORKS),
                    help="comma list of network keys from config.NETWORKS "
                         f"(default: all - {', '.join(config.NETWORKS)})")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    names = [n.strip() for n in args.networks.split(",") if n.strip()]
    unknown = set(names) - set(config.NETWORKS)
    if unknown:
        raise SystemExit(f"unknown network(s): {', '.join(sorted(unknown))} "
                          f"- choose from {', '.join(config.NETWORKS)}")

    for name in names:
        print(f"\n=== {name} - {config.NETWORKS[name]['label']} ===")
        if args.stage in (None, "mirror"):
            engine.mirror_network(name)
        if args.stage in (None, "build"):
            engine.build_network(name)

    print(f"\ndone -> {config.DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
