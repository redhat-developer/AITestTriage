"""URL parsing utilities for extracting base_dir from prow/gcsweb links."""

import re
import logging
from typing import Optional
from config.settings import settings

logger = logging.getLogger(__name__)

_PROW_URL_PREFIX = f"https://prow.ci.openshift.org/view/gs/{settings.gcs_bucket_name}"
_GCSWEB_URL_PREFIX = f"https://gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com/gcs/{settings.gcs_bucket_name}"

# Pattern for prow URLs
_PROW_PATTERN = re.compile(
    rf'{re.escape(_PROW_URL_PREFIX)}/'
    r'((?:logs|pr-logs)/[^|>\s/]+(?:/[^|>\s/]+)*)'
)

# Pattern for gcsweb URLs - extract base_dir up to job ID
_GCSWEB_PATTERN = re.compile(
    rf'{re.escape(_GCSWEB_URL_PREFIX)}/'
    r'((?:logs|pr-logs)(?:/[^/\s|>]+)*/\d+)'
)


def build_prow_url(base_dir: str) -> str:
    """Build a Prow URL using the configured GCS bucket."""
    return f"{_PROW_URL_PREFIX}/{base_dir}"


def extract_base_dir(text: str) -> Optional[str]:
    """Extract the GCS base_dir from a prow or gcsweb URL in the given text.

    Args:
        text: Text that may contain a prow or gcsweb URL.

    Returns:
        The extracted base_dir string, or None if no valid URL was found.
    """
    prow_match = _PROW_PATTERN.search(text)
    if prow_match:
        return prow_match.group(1)

    gcsweb_match = _GCSWEB_PATTERN.search(text)
    if gcsweb_match:
        base_dir = gcsweb_match.group(1)
        logger.info(f"Constructed prow link from gcsweb: {build_prow_url(base_dir)}")
        return base_dir

    return None
