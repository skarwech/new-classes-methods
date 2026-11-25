"""Words that belong to working documents, not to a public site or repository."""

from __future__ import annotations

import re

# Whole words only: "apart from" must not trip "part f", nor "synthesis" trip "thesis".
WORKING_WORDING = re.compile(
    r"\b(?:catalogue|competitors?|thesis|brief|drafts?|drafting)\b|\bpart [b-f]\b",
    re.IGNORECASE,
)

# The same without "thesis": a cited thesis is a legitimate row in the data itself.
PUBLIC_DATA_WORDING = re.compile(
    r"\b(?:catalogue|competitors?)\b|\bpart \w", re.IGNORECASE
)
