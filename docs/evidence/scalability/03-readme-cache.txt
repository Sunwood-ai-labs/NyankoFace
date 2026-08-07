NyankoFace README metadata cache verification
Captured: 2026-07-14T12:36Z

Configuration:
README_CACHE_TTL_SECONDS=300
PAGE_SIZE=48

Cold directory request:
HTTP_STATUS=200
README_FETCHES=24

Warm directory request inside the five-minute TTL:
HTTP_STATUS=200
README_FETCHES=0

The current directory contains 24 Spaces. Pagination constrains enrichment to
the current page, so at most 48 README files are considered per request.
