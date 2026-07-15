from __future__ import annotations

from urllib.parse import urlparse

from harbor_agent.models import Program


DETAIL_MICROSITE_HOSTS = {
    "datascience.hku.hk",
    "msba.nus.edu.sg",
    "mscfin.nus.edu.sg",
    "mscmarketing.nus.edu.sg",
    "mim.nus.edu.sg",
    "maefs.eduhk.hk",
    "mastem.eduhk.hk",
    "msccgc.hkbu.edu.hk",
    "mscbm.hkbu.edu.hk",
    "mscaaf.hkbu.edu.hk",
}

APPLICATION_PORTAL_HOSTS = {
    "portal.hku.hk",
    "www.gradsch.cuhk.edu.hk",
    "banweb.cityu.edu.hk",
    "iss.hkbu.edu.hk",
    "apply.ln.edu.hk",
    "www38.polyu.edu.hk",
    "gradapp.nus.edu.sg",
    "venus.wis.ntu.edu.sg",
    "w5.ab.ust.hk",
    "admissions.smu.edu.sg",
    "admission.sutd.edu.sg",
}

GENERIC_PROGRAM_URL_PATTERNS = (
    "programme-list",
    "program-list",
    "programmes-list",
    "programs-list",
    "taught-postgraduate-programmes",
    "taught-postgraduate-programs",
    "graduate-admissions",
    "postgraduate-admissions",
    "prog-crs.hkust.edu.hk/pgprog/",
    "graduate-programmes",
    "graduate-programs",
    "/pg/tpg/programmes",
    "acadprog/postgrad",
    "admissions/graduate",
    "masters.smu.edu.sg/programmes",
    "/admissions",
    "/admission",
    "/programmes?",
    "/programs?",
    "/programme/index",
    "/program/index",
)

GENERIC_APPLICATION_URL_PATTERNS = GENERIC_PROGRAM_URL_PATTERNS


def is_generic_program_url(url: str | None) -> bool:
    if not url:
        return True
    normalized = str(url).strip().lower()
    if not normalized:
        return True
    parsed = urlparse(normalized)
    if parsed.netloc in DETAIL_MICROSITE_HOSTS:
        return False
    path_and_query = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
    if path_and_query in {"", "/"}:
        return True
    if parsed.netloc == "masters.smu.edu.sg" and parsed.path.startswith("/programmes/"):
        return False
    if parsed.netloc == "www.ntu.edu.sg" and "/admissions/graduate-studies/" in parsed.path:
        return False
    if parsed.netloc == "prog-crs.hkust.edu.hk" and "/pgprog/" in parsed.path:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 3:
            return False
    if parsed.netloc in {"sph.nus.edu.sg", "lkyspp.nus.edu.sg"} and "/graduate-programmes/" in parsed.path:
        return False
    if parsed.netloc == "www.sutd.edu.sg" and parsed.path.startswith("/programme-listing/"):
        return False
    if "prog-crs.hkust.edu.hk/pgprog/" in normalized and "/msc-" in normalized:
        return False
    return any(pattern in normalized for pattern in GENERIC_PROGRAM_URL_PATTERNS)


def is_generic_application_url(url: str | None) -> bool:
    if not url:
        return True
    normalized = str(url).strip().lower()
    if not normalized:
        return True
    parsed = urlparse(normalized)
    if parsed.netloc in APPLICATION_PORTAL_HOSTS:
        return False
    if parsed.netloc == "www.eduhk.hk" and parsed.path.startswith("/acadprog/online/"):
        return False
    if parsed.netloc in DETAIL_MICROSITE_HOSTS:
        return False
    if normalized.rstrip("/") == "https://prog-crs.hkust.edu.hk/pgprog":
        return True
    if "prog-crs.hkust.edu.hk/pgprog/" in normalized and "/msc-" in normalized:
        return False
    return any(pattern in normalized for pattern in GENERIC_APPLICATION_URL_PATTERNS)


def has_program_detail_page(program: Program) -> bool:
    return not is_generic_program_url(str(program.official_program_url) if program.official_program_url else None)


def has_application_entry(program: Program) -> bool:
    if not program.application_url:
        return False
    application_url = str(program.application_url).strip().lower()
    detail_url = str(program.official_program_url or "").strip().lower()
    if detail_url and application_url.rstrip("/") == detail_url.rstrip("/"):
        return False
    if is_generic_application_url(application_url):
        return False
    parsed = urlparse(application_url)
    if parsed.netloc in APPLICATION_PORTAL_HOSTS:
        return True
    if parsed.netloc == "www.eduhk.hk" and parsed.path.startswith("/acadprog/online/"):
        return True
    return any(token in application_url for token in ("apply", "application", "admission", "onlineapp", "portal", "login", "amsappl", "eadmission"))


def student_program_url(program: Program) -> str | None:
    if has_program_detail_page(program):
        return str(program.official_program_url)
    return None


def student_application_url(program: Program) -> str | None:
    if has_application_entry(program):
        return str(program.application_url)
    return None
