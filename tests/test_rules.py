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


def test_languages():
    lang = lambda t, d="": any(r["code"] == "language" for r in E.assess({"title": t, "description": d})["reasons"])
    assert lang("Claims Analyst - Slovak")
    assert lang("Customer Support (Multilingual with Italian)")
    assert lang("Analyst", "German language skills (written and spoken).")
    assert lang("Analyst", "Fluency in Irish is essential.")
    assert not lang("Customer Service Advisor - Irish Life")
    assert not lang("Analyst", "We are a proudly native Irish company.")
    assert not lang("Analyst", "German language skills are a plus.")
    assert not lang("Analyst", "Fluent English and Hindi.")
    assert lang("Profil Francophone & Televendeur")
    assert lang("Ionadaí Seirbhíse", "Oibreoidh tú agus foghlaimeoidh tú agus beidh tú agus " * 2)
    assert not lang("Therapist", "Careers agus Jobs. Equal opportunities agus inclusion.")


def test_places():
    from scraper import filters as F
    assert not F.is_in_ireland({"title": "Agent", "location": "Le Kram, Kheireddine, Tunis"})
    assert not F.is_in_ireland({"title": "Call Centre Agent", "location": "ENNISKILLEN"})
    assert F.is_in_ireland({"title": "Analyst", "location": "Ennis, Co. Clare"})
    assert F.is_in_ireland({"title": "Analyst", "location": "Dublin 2, Ireland"})


def test_tcs_style_page_keeps_its_text():
    from scraper.ats_extra import _readable_text
    words = " ".join(["Contact Centre Associate. Location Letterkenny, County Donegal, Ireland."] * 8)
    page = f"<html><body><form id='aspnetForm'><div>{words}</div></form></body></html>"
    assert "Letterkenny" in _readable_text(page)


def test_job_address():
    from scraper.run import job_address as A
    cm = "https://www.candidatemanager.net/cm/p/pJobDetails.aspx?mid=X&jid="
    assert A(cm + "1") != A(cm + "2")                      # TCS jobs stay apart
    assert A("https://stripe.com/jobs/search?gh_jid=1") != A("https://stripe.com/jobs/search?gh_jid=2")
    assert A("https://careers.axa.com/jobs/28794?lang=en-us") == A("https://careers.axa.com/jobs/28794/")
    assert A("https://x.com/job/1?utm_source=rss") == A("https://x.com/job/1")


def test_same_title_no_location_kept_apart():
    from scraper.run import dedupe_key as K
    a = {"company": "TCS Ireland", "title": "Customer Service Representative", "location": "", "description": "Ref 120826 pensions team"}
    b = dict(a, description="Ref 221026 energy team")
    assert K(a) != K(b) and K(a) == K(dict(a))
    assert K(dict(a, location="Dublin")) == K(dict(b, location="Dublin"))


def test_bpo_names():
    from scraper.run import BPO
    for n in ("TCS Ireland", "Covalen", "Infosys BPM", "HCLTech Ireland", "Version 1", "TELUS Digital"):
        assert BPO.search(n), n
    for n in ("Irish Life Group", "Version 10 Ltd", "Sunrise Ltd", "Excel Recruitment"):
        assert not BPO.search(n), n


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
