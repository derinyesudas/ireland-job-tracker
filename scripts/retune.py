"""
Broaden the scoring beyond analyst roles.

She is applying for white-collar work generally now - pensions and insurance
administration, claims, customer service, back office, contract roles, and
anything that wants the Excel-and-accuracy work she did at TCS. The scorer
only ever knew about analyst families, so everything else scored near zero and
sat in the weak band regardless of how good a fit it was.

The weights live in profile/derin.json.enc, which is why this runs on your
machine and not in the cloud: it needs the vault key.

Nothing is written blind. The script prints what it will change, re-scores the
live board both ways so you can see which jobs actually move, and only then
asks whether to save. --dry-run stops before the question.

    set TRACKER_KEY=your-vault-passphrase
    python -m scripts.retune --dry-run
    python -m scripts.retune
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import crypt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROFILE_ENC = ROOT / "profile" / "derin.json.enc"
KEYS = ROOT / "data" / "keys.json"
JOBS = ROOT / "data" / "jobs.json"

# --------------------------------------------------------------------------
# What changes, and why. Every family is matched against the TITLE only - the
# scorer stopped scanning whole adverts for a reason, and nothing here should
# quietly put that back.
# --------------------------------------------------------------------------

NEW_EVIDENCE = {
    "tcs_admin": "a year of pensions and insurance record administration at TCS, "
                 "to documented procedures at 99% accuracy",
    "tcs_client": "single point of contact for a US insurer's queries, by phone and email",
    "frontline": "ten months front-line customer service at D-Mart, plus the TCS client desk",
    "office_general": "a finance degree, an analytics MSc and a year of process work "
                      "in a regulated back office",
}

NEW_FAMILIES = {
    # Closest to what she actually did. Should outrank the analyst families
    # when the title says so, because this is the job she has already held.
    "pensions_insurance_admin": {
        "terms": ["pensions administrator", "pension administrator", "pensions administration",
                  "life and pensions", "policy administrator", "policy administration",
                  "claims handler", "claims administrator", "claims assessor", "claims analyst",
                  "claims executive", "claims specialist", "underwriting assistant",
                  "annuity", "retirement administrator", "scheme administrator",
                  "member services", "policy services", "new business administrator"],
        "weight": 30, "evidence": "tcs_admin",
    },
    "financial_ops_admin": {
        "terms": ["fund administrator", "fund accountant", "transfer agency",
                  "investment operations", "investment administrator", "settlements",
                  "custody", "middle office", "back office", "operations administrator",
                  "operations associate", "operations analyst", "payroll administrator",
                  "payroll associate", "accounts assistant", "accounts payable",
                  "accounts receivable", "finance assistant", "finance administrator"],
        "weight": 26, "evidence": "tcs_admin",
    },
    "client_service": {
        "terms": ["customer service", "customer support", "customer care",
                  "customer operations", "customer experience", "client service",
                  "client support", "client onboarding", "contact centre", "call centre",
                  "service desk", "helpdesk", "customer advisor", "customer advisor",
                  "service advisor", "member support", "policyholder services"],
        "weight": 22, "evidence": "frontline",
    },
    "office_support": {
        "terms": ["administrator", "administrative assistant", "office administrator",
                  "business support", "team administrator", "coordinator",
                  "project administrator", "project coordinator", "data entry",
                  "records administrator", "document controller", "receptionist",
                  "scheduler", "planner"],
        "weight": 18, "evidence": "office_general",
    },
    "sales_support": {
        "terms": ["sales support", "sales administrator", "inside sales",
                  "account administrator", "account coordinator", "broker support",
                  "intermediary support", "bid coordinator"],
        "weight": 16, "evidence": "tcs_client",
    },
}

# Terms to fold into families that already exist, if they are there.
EXTEND = {
    "data_migration": ["data migration", "data quality", "data validation",
                       "data steward", "data governance", "master data"],
}

# Adverts that say training is provided and experience is not required are
# worth points in their own right - that is the whole shape of job she can get.
NO_EXPERIENCE_TERMS = [
    "no experience necessary", "no experience required", "no previous experience",
    "full training provided", "training will be provided", "training is provided",
    "we will train", "on the job training", "no prior experience",
    "suitable for graduates", "open to graduates", "career changers welcome",
]


def preview(old: dict, new: dict) -> None:
    o, n = old["target_role_families"], new["target_role_families"]
    print("\n  ROLE FAMILIES")
    for name in sorted(set(n) - set(o)):
        f = n[name]
        print(f"    + {name:26} weight {f['weight']:3}  ({len(f['terms'])} titles)")
        print(f"        e.g. {', '.join(f['terms'][:4])}")
    for name in sorted(set(o) & set(n)):
        if o[name] != n[name]:
            added = [t for t in n[name]["terms"] if t not in o[name]["terms"]]
            if o[name]["weight"] != n[name]["weight"]:
                print(f"    ~ {name:26} weight {o[name]['weight']} -> {n[name]['weight']}")
            if added:
                print(f"    ~ {name:26} +{len(added)} titles: {', '.join(added[:5])}")
    if "no_experience_needed" in new:
        print(f"\n  NEW BONUS: no_experience_needed "
              f"({len(new['no_experience_needed']['terms'])} phrases, "
              f"{new['no_experience_needed']['bonus']} pts)")
    print("\n  Unchanged: tools, operational vocabulary, locations, sponsorship, "
          "hard exclusions.")


def rescore(profile: dict, limit: int = 0) -> dict:
    """Score the live board with a given profile. Returns {id: (score, band)}."""
    from scraper import score as S
    if not JOBS.exists():
        return {}
    jobs = json.loads(JOBS.read_text(encoding="utf-8"))
    jobs = [j for j in jobs if not j.get("closed")]
    if limit:
        jobs = jobs[:limit]
    out, failed, first_error = {}, 0, ""
    for j in jobs:
        try:
            r = S.score_job(j, profile, {})
            out[j["id"]] = (r["score"], r["band"], j.get("title", ""), j.get("company", ""))
        except Exception as exc:
            failed += 1
            first_error = first_error or f"{type(exc).__name__}: {exc}"
    # Swallowing these would report "0 jobs move" for a profile that in fact
    # cannot be scored at all - the comparison would look reassuring and mean
    # nothing. Say so instead.
    if failed:
        print(f"\n  WARNING: {failed} of {len(jobs)} jobs could not be scored "
              f"({first_error}).")
        if not out:
            print("  Nothing scored at all - the preview below is meaningless. "
                  "Do not save.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="show the change and its effect, write nothing")
    args = ap.parse_args()

    passphrase = crypt._passphrase("Vault passphrase: ")
    if not passphrase:
        print("no passphrase given")
        return 1
    try:
        data_key = crypt.unlock(passphrase, KEYS)
    except Exception as exc:
        print(f"could not unlock: {exc}")
        return 1

    old = json.loads(crypt.decrypt_bytes(PROFILE_ENC.read_bytes(), data_key))
    new = copy.deepcopy(old)

    fams = new.setdefault("target_role_families", {})
    for name, fam in NEW_FAMILIES.items():
        if name in fams:
            print(f"  note: {name} already exists - leaving its weight alone, "
                  f"merging titles only")
            have = set(fams[name].get("terms", []))
            fams[name]["terms"] = fams[name].get("terms", []) + \
                [t for t in fam["terms"] if t not in have]
        else:
            fams[name] = dict(fam)
    for name, extra in EXTEND.items():
        if name in fams:
            have = set(fams[name].get("terms", []))
            fams[name]["terms"] += [t for t in extra if t not in have]
    new.setdefault("evidence", {}).update(NEW_EVIDENCE)
    new["no_experience_needed"] = {"terms": NO_EXPERIENCE_TERMS, "bonus": 6}

    preview(old, new)

    before, after = rescore(old), rescore(new)
    if before and after:
        moved = [(after[i][0] - before[i][0], before[i], after[i])
                 for i in before if i in after and after[i][0] != before[i][0]]
        moved.sort(key=lambda x: -x[0])
        ups = [m for m in moved if m[0] > 0]
        downs = [m for m in moved if m[0] < 0]
        print(f"\n  EFFECT ON THE LIVE BOARD: {len(ups)} jobs rise, "
              f"{len(downs)} fall, {len(before) - len(moved)} unchanged")
        for d, b, a in ups[:12]:
            print(f"    +{d:3}  {b[0]:3}->{a[0]:3}  {a[1]:9} {a[3][:20]:20} {a[2][:44]}")
        if downs:
            print("    -- falls --")
            for d, b, a in downs[:5]:
                print(f"    {d:4}  {b[0]:3}->{a[0]:3}  {a[1]:9} {a[3][:20]:20} {a[2][:44]}")
    else:
        print("\n  (no local data/jobs.json - run the scraper first to preview the effect)")

    if args.dry_run:
        print("\n  dry run - nothing written.")
        return 0

    print()
    if input("  Write this to the encrypted profile? [y/N] ").strip().lower() != "y":
        print("  nothing written.")
        return 0

    backup = PROFILE_ENC.with_suffix(".enc.bak")
    backup.write_bytes(PROFILE_ENC.read_bytes())
    PROFILE_ENC.write_bytes(crypt.encrypt_bytes(
        json.dumps(new, indent=2, ensure_ascii=False).encode("utf-8"), data_key))
    print(f"  written. Previous profile kept at {backup.name} - delete it once "
          f"you are happy, it is encrypted but it is still a spare copy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
