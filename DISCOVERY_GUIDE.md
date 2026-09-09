# Source Discovery, Validation & Cost Control

The production architecture uses a **zero-cost canonical manifest** followed by
**transport validation during the first real fetch**.

## Approved sources

1. Nigeria Property Centre — direct requests from GitHub Actions.
2. PropertyPro Nigeria — Zyte browser HTML.
3. Estate Intel — Zyte browser HTML, **public pages only**.

Premium, login-gated, or account-only Estate Intel data is never bypassed.

## Discovery layer

`discover_sources.py` builds the canonical URL manifest without paid requests.
It covers the 9 monitored nodes and the required apartment/land categories.
Apartment bedroom bands 1–5 are classification targets, **not separate URLs**.

The manifest contains only approved canonical URLs. It does not invent listing
URLs or make speculative bedroom-specific URLs.

## Transport validation

The first production fetch of each unique category URL is the validation gate:

1. host must match the approved source;
2. Estate Intel premium/login paths are rejected;
3. the transport must return HTML;
4. only then is the HTML parsed for comparable listings.

This avoids paying twice for a separate validation request.

## Cost controls

- one paid fetch per unique PropertyPro/Estate Intel category URL;
- one page per category by default;
- up to 12 recent comparable cards per category;
- two concurrent workers by default;
- detail-page fetching disabled by default;
- Zyte 401/402/403 is fail-fast and never retried.

The goal is a measurable comparable sample, not maximum listing volume.
