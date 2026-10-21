"""Guards the filter rules. Run: python tests/test_rules.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper import eligible as E  # noqa: E402


def status(title, desc=""):
    return E.assess({"title": title, "description": desc})["status"]


def test_years():
    assert E.years_required("Minimum 3 years of experience in client services")[0] == 3
    assert E.years_required("Business Analyst with 5+ years experience to join")[0] == 5
    assert E.years_required("Has 7+ years of sales, strategy and operations experience")[0] == 7
    assert E.years_required("Minimum 2 years experience preferred. Minimum 3 years of experience required.")[0] == 3
    assert E.years_required("3+ years experience desirable") is None
    assert E.years_required("We have 25 years' experience in insurance.") is None


def test_sales_and_retail():
    for t in ("Account Executive - On Trade", "Insurance Advisor", "Recruitment Coordinator", "Trainee Buyer"):
        assert status(t) == "blocked", t
    for t in ("Retail Banking Graduate Programme 2027", "Sales Support Executive", "Pensions Administrator"):
        assert status(t) != "blocked", t


def test_experience_blocks():
    assert status("Claims Handler", "Minimum 4 years of experience in claims required.") == "blocked"
    assert status("Claims Handler", "No experience needed.") != "blocked"


def test_learned_words():
    from scripts.feedback import learned_words
    hid = lambda t, r="wrong field": {"kind": "hidden", "title": t, "reason": r}
    log = [hid("Procurement Analyst"), hid("Senior Procurement Lead"), hid("Procurement Officer"),
           hid("Treasury Analyst", "too senior"), hid("Treasury Officer", "too senior"), hid("Treasury Clerk", "too senior")]
    assert learned_words(log) == {"procurement"}
    assert learned_words(log + [{"kind": "applied", "title": "Procurement Assistant"}]) == set()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
