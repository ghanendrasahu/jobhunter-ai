"""Job source registry.

Importing this package registers every bundled source in
``jobhunter.domains.search.sources.base``.
"""

from jobhunter.domains.search.sources.cutshort import CutshortSource  # noqa: F401  (registers itself)
from jobhunter.domains.search.sources.foundit import FounditSource  # noqa: F401  (registers itself)
from jobhunter.domains.search.sources.google_jobs import GoogleJobsSource  # noqa: F401  (registers itself)
from jobhunter.domains.search.sources.hirist import HiristSource  # noqa: F401  (registers itself)
from jobhunter.domains.search.sources.indeed import IndeedSource  # noqa: F401  (registers itself)
from jobhunter.domains.search.sources.internshala import InternshalaSource  # noqa: F401  (registers itself)
from jobhunter.domains.search.sources.linkedin import LinkedInSource  # noqa: F401  (registers itself)
from jobhunter.domains.search.sources.naukri import NaukriSource  # noqa: F401  (registers itself)

__all__ = [
    "CutshortSource",
    "FounditSource",
    "GoogleJobsSource",
    "HiristSource",
    "IndeedSource",
    "InternshalaSource",
    "LinkedInSource",
    "NaukriSource",
]
