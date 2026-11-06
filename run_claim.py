"""Process one OMC claim against an EBM extract from the command line.

Example:
  python run_claim.py --claim sample_data/claim_sample.xlsx \
      --ebm sample_data/ebm_extract_sample.csv --rura sample_data/rura_prices.csv \
      --tin 100007664 --name "SAMPLE OMC" --from 2026-06-01 --to 2026-06-30 \
      --account "BK A/C ..." --processor "Ntihemuka David" --out result.xlsx
"""
import argparse
import json

from engine.config import Settings
from engine.pipeline import process, summarise


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claim", required=True)
    ap.add_argument("--ebm", required=True)
    ap.add_argument("--rura", help="RURA price list: product, effective_from, price")
    ap.add_argument("--history", help="Earlier paid lines, to catch invoices claimed twice")
    ap.add_argument("--tin")
    ap.add_argument("--name", default="")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--account", default="")
    ap.add_argument("--processor", default="")
    ap.add_argument("--rate", type=float, help="Official subsidy rate RWF/L (default: rate in the claim)")
    ap.add_argument("--out", default="result.xlsx")
    a = ap.parse_args()

    settings = Settings(official_subsidy_rate=a.rate)
    meta = {"tin": a.tin, "name": a.name, "period_start": a.start, "period_end": a.end,
            "account": a.account, "processor": a.processor}
    lines, problems, xlsx = process(a.claim, a.ebm, meta, a.rura, a.history, settings)
    for p in problems:
        print("NOTE:", p)
    if lines is None:
        raise SystemExit("Stopped: fix the file problems above.")
    with open(a.out, "wb") as f:
        f.write(xlsx)
    print(json.dumps(summarise(lines), indent=2))
    print("Report written to", a.out)


if __name__ == "__main__":
    main()
