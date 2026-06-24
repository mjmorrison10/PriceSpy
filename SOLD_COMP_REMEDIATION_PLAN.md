# PriceSpy Sold-Comp Remediation Plan

Goal: make `recent_sold` represent **validated sold comps**, not just any listing that looks sold-ish.

## Core principle
A listing should contribute to medians, trend, velocity, flip score, and condition stats **only if it passes sold-comp validation**.

---

## 1) Files and functions to change

### `server.py`

#### Existing functions to keep but refactor
- `_ebay_sold_listings(query, condition="all", limit=100)`
- `_scrape_ebay_sold_fallback(query, condition="all", limit=60)`
- `_do_search(...)`
- `_generate_trend(...)`
- `_compute_stats(...)`
- `_stats_by_condition(...)`
- `_filter_by_condition(...)`
- `_analyze_flip(...)`
- `api_search()`
- `api_recalculate()`

#### New helper functions to add
- `_extract_item_id_from_url(url: str) -> str | None`
- `_normalize_sold_comp(raw: dict, source: str) -> dict`
- `_normalize_active_comp(raw: dict) -> dict`
- `_build_active_item_id_set(active_items: list[dict]) -> set[str]`
- `_category_specific_rejects(query: str, title: str) -> list[str]`
- `_validate_sold_comp(comp: dict, query: str, active_ids: set[str], today_ymd: str) -> dict`
- `_sold_source_rank(source: str) -> int`
- `_sold_comp_quality_score(comp: dict) -> int`
- `_merge_duplicate_sold_comps(comps: list[dict]) -> list[dict]`
- `_partition_sold_comps(comps: list[dict]) -> tuple[list[dict], list[dict]]`
- `_build_sold_verification_url(query: str, title: str, item_id: str | None) -> str`

### `static/js/app.js`

#### Existing functions to update
- `buildListings(res, d)`
- `buildVerification(res, d)`
- `renderAll(d)`
- `recalcAfterManualDelete()`
- `recalcFromExistingData()`

#### New frontend helpers to add
- `soldCompStatusBadge(comp)`
- `soldCompWarnings(comp)`
- `openSoldVerification(comp, query)`
- `renderExcludedComps(container, excluded)`

### `templates/index.html`
No major structural changes required, but you may want a small legend block for badges.

---

## 2) Data model changes

### Sold comp shape (normalized)
All sold candidates should be normalized to this structure before filtering/stats:

```python
{
  "title": str,
  "price": float,
  "shipping": float | None,
  "condition": str,

  "url": str,
  "verification_url": str,
  "url_type": "view_item" | "sold_search" | "search_card" | "none",

  "source": "ebay_browse" | "ebay_finding" | "ebay_html" | "pricecharting",
  "source_confidence": "high" | "medium" | "low",

  "item_id": str | None,
  "legacy_item_id": str | None,
  "variation_id": str | None,

  "sold_date": str | None,
  "sold_date_raw": str | None,
  "sold_date_valid": bool,

  "listing_type": str | None,
  "selling_state": str | None,
  "is_multi_variation": bool | None,

  "active_overlap": bool,
  "comp_valid": bool,
  "reject_reasons": list[str],
  "warning_reasons": list[str],

  "relevance": float,
}
```

### Active comp shape (normalized)

```python
{
  "title": str,
  "price": float,
  "shipping": float | None,
  "condition": str,
  "url": str,
  "item_id": str | None,
  "is_auction": bool,
  "source": "ebay_browse",
  "relevance": float,
}
```

---

## 3) Backend implementation checklist

## Step A — item ID extraction

### Add `_extract_item_id_from_url`
Should support:
- `/itm/123456789012`
- `/itm/title/123456789012`
- `?item=123456789012`

Pseudo:

```python
def _extract_item_id_from_url(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r'/itm/(?:[^/]+/)?(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'item=(\d+)', url)
    if m:
        return m.group(1)
    return None
```

---

## Step B — normalize sold candidates by source

### Replace current raw-dict merging with normalization

#### Browse candidate mapping
Current source: `_ebay_sold_listings -> fetch_browse()`

Normalize as:

```python
{
  "title": it.get("title", ""),
  "price": float(...),
  "shipping": None,
  "condition": canonical_condition,
  "url": it.get("itemWebUrl", ""),
  "verification_url": _build_sold_verification_url(query, title, item_id),
  "url_type": "view_item",
  "source": "ebay_browse",
  "source_confidence": "low",
  "item_id": _extract_item_id_from_url(url),
  "legacy_item_id": _extract_item_id_from_url(url),
  "variation_id": None,
  "sold_date": safe_date(it.get("itemEndDate")),
  "sold_date_raw": it.get("itemEndDate"),
  "sold_date_valid": False,  # set later
  "listing_type": None,
  "selling_state": None,
  "is_multi_variation": None,
  "active_overlap": False,
  "comp_valid": False,
  "reject_reasons": [],
  "warning_reasons": [],
  "relevance": existing_relevance,
}
```

#### Finding candidate mapping
Current source: `_ebay_sold_listings -> fetch_finding()`

Normalize as:

```python
{
  "source": "ebay_finding",
  "source_confidence": "medium",
  "url": it.get("viewItemURL", [""])[0],
  "url_type": "view_item",
  "sold_date": safe_date(it.get("listingInfo", [{}])[0].get("endTime", "")),
  "sold_date_raw": it.get("listingInfo", [{}])[0].get("endTime", ""),
  "listing_type": it.get("listingInfo", [{}])[0].get("listingType"),
  "selling_state": it.get("sellingStatus", [{}])[0].get("sellingState"),
  "is_multi_variation": bool(it.get("isMultiVariationListing", [False])[0]) if isinstance(it.get("isMultiVariationListing"), list) else bool(it.get("isMultiVariationListing")),
  ...
}
```

#### HTML fallback mapping
Current source: `_scrape_ebay_sold_fallback()`

Normalize as:
- `source = ebay_html`
- `source_confidence = high`
- `url_type = search_card`
- `sold_date` from endedDate text

#### PriceCharting mapping
Normalize as:
- `source = pricecharting`
- `source_confidence = low`
- `url_type = none`
- never allow to open as a sold eBay listing

---

## Step C — build active item ID set

After active fetch/relevance filtering:

```python
def _build_active_item_id_set(active_items: list[dict]) -> set[str]:
    ids = set()
    for it in active_items:
        iid = _extract_item_id_from_url(it.get("url", ""))
        if iid:
            ids.add(iid)
    return ids
```

This is needed to catch the exact problem already observed live: same item IDs in sold and active.

---

## Step D — category-specific reject rules

### Add `_category_specific_rejects(query, title)`
Return a list of reasons, not a boolean.

#### Electronics rules
Reject when query targets a phone model and title contains:
- `pro max` when query is `pro`
- wrong generation (`12` vs `13`)
- wrong storage if query specifies storage
- `broken`, `cracked`, `read` unless query asks for that

#### Console / gaming hardware rules
Reject when query is console-like and title contains:
- `dock`
- `case`
- `charger`
- `shell`
- `thumb grip`
- `buttons`
- `console only` unless query asks for tablet/console only
- `bundle` or `lot` unless query asks for it

#### Tool rules
Reject when title contains:
- `chuck`
- `switch`
- `label`
- `gear shifter`
- `housing`
- `case only`
- `replacement`
- `part`

#### Trading card rules
Reject or segregate if:
- `psa`, `bgs`, `cgc` and query does not ask graded
- `lot`, `collection`, `binder`, `trio`
- `base set 2` when query asks base set
- `japanese` when query implies english raw

#### Book rules
Reject if:
- `paperback` when query says hardcover
- `guide`, `casebook`, `study`, `cooking`, `entertaining`
- `set of` / multi-book set unless requested

#### Shoe rules
Reject if:
- `toddler`, `gs`, `youth`, `baby` when query implies adult pair
- wrong style code / wrong gender model if query specific

---

## Step E — sold-comp validation function

### Add `_validate_sold_comp`
This is the central gatekeeper.

Pseudo:

```python
def _validate_sold_comp(comp, query, active_ids, today_ymd):
    rejects = []
    warns = []

    if not comp.get("title"):
        rejects.append("missing_title")

    if not comp.get("price") or comp["price"] <= 0:
        rejects.append("invalid_price")

    sold_date = comp.get("sold_date")
    if not sold_date:
        rejects.append("missing_sold_date")
    elif not re.match(r"\d{4}-\d{2}-\d{2}$", sold_date):
        rejects.append("bad_sold_date_format")
    elif sold_date > today_ymd:
        rejects.append("future_sold_date")

    if comp.get("item_id") and comp["item_id"] in active_ids:
        rejects.append("active_overlap")
        comp["active_overlap"] = True

    if comp.get("relevance", 0) < 0.55:
        rejects.append("low_relevance")

    rejects.extend(_category_specific_rejects(query, comp.get("title", "")))

    if comp.get("source") == "ebay_browse":
        warns.append("browse_sold_low_confidence")

    if comp.get("source") == "pricecharting":
        rejects.append("non_ebay_sold_source")

    if comp.get("is_multi_variation"):
        warns.append("multi_variation_possible")

    comp["sold_date_valid"] = sold_date is not None and sold_date <= today_ymd if sold_date else False
    comp["reject_reasons"] = rejects
    comp["warning_reasons"] = warns
    comp["comp_valid"] = len(rejects) == 0
    return comp
```

### Important policy choice
For now, I recommend:
- `ebay_browse` comps may remain visible, but **must not** enter stats unless they fully validate.
- `pricecharting` comps should be visible only as low-confidence fallback and **excluded from stats** if you want strict eBay-only correctness.

---

## Step F — duplicate merge policy

### Replace URL-only dedupe
Use a multi-key strategy:

```python
def sold_identity_key(comp):
    if comp.get("item_id") and comp.get("variation_id"):
        return f"{comp['item_id']}|{comp['variation_id']}"
    if comp.get("item_id"):
        return f"{comp['item_id']}|base"
    if comp.get("url"):
        return canonicalize_url(comp["url"])
    return f"{normalize_title(comp['title'])}|{comp['price']}|{comp.get('sold_date') or ''}"
```

### Keep best duplicate
Pseudo:

```python
def _sold_source_rank(source):
    ranks = {
      "ebay_html": 4,
      "ebay_finding": 3,
      "ebay_browse": 2,
      "pricecharting": 1,
    }
    return ranks.get(source, 0)


def _sold_comp_quality_score(comp):
    score = 0
    score += _sold_source_rank(comp["source"]) * 100
    if comp.get("sold_date_valid"):
        score += 40
    if not comp.get("active_overlap"):
        score += 30
    score += int((comp.get("relevance") or 0) * 20)
    score -= len(comp.get("reject_reasons", [])) * 25
    return score
```

This ensures you do not keep a weak Browse record when a better Finding/HTML version exists.

---

## Step G — use only validated comps in stats

### In `_do_search(...)`
Current flow:
- fetch raw sold
- relevance filter
- condition filter
- stats

Change to:

```python
sold_candidates = fetch sold candidates
active_candidates = fetch active candidates

active_items = _filter_by_relevance(active_candidates, q)
active_ids = _build_active_item_id_set(active_items)

today_ymd = datetime.now(timezone.utc).strftime("%Y-%m-%d")

sold_candidates = _filter_by_relevance(sold_candidates, q)
sold_candidates = [_normalize_sold_comp(it, it["source"]) for it in sold_candidates]
sold_candidates = [_validate_sold_comp(it, q, active_ids, today_ymd) for it in sold_candidates]
sold_candidates = _merge_duplicate_sold_comps(sold_candidates)

sold_valid = [it for it in sold_candidates if it["comp_valid"]]
sold_excluded = [it for it in sold_candidates if not it["comp_valid"]]

sold_filtered = _filter_by_condition(sold_valid, filter_condition)
active_filtered = _filter_by_condition(active_items, filter_condition)
```

Then:
- `sold_summary` should use `sold_filtered`
- `condition_sold` should use `sold_valid`
- `trend` should use only `sold_filtered`
- `velocity` should use only `sold_filtered`
- `recent_sold` can either:
  - show only valid sold comps
  - or show valid first plus `excluded_sold` separately

### Return extra response keys
Add to result JSON:

```python
"recent_sold": recent_sold_valid,
"excluded_sold": sold_excluded,
"sold_validation_summary": {
  "valid_count": len(sold_valid),
  "excluded_count": len(sold_excluded),
  "excluded_reasons": counts_by_reason,
}
```

---

## Step H — chart/trend hardening

### `_generate_trend(...)`
Do not change much internally yet.
Just ensure it receives only validated sold comps.

### New minimums
Allow trend only if:
- at least 3 validated sold comps
- at least 2 unique valid weeks
- no future dates

If not enough:
- return `[]`
- plus response flag:

```python
"trend_status": {
  "available": False,
  "reason": "not_enough_valid_dated_sales"
}
```

---

## 4) Frontend implementation checklist

## Step I — stop opening sold comps as proof

### In `buildListings(res, d)`
Current sold rows open `it.url`.

Change behavior:
- sold row click opens `it.verification_url` if present
- add separate icon/button:
  - `🔗 Listing page` opens raw `it.url`
  - `✅ Verify sold search` opens `it.verification_url`

If `url_type == "view_item"`, show badge:
- `View Item URL only`

---

## Step J — show comp badges and warnings

For each sold comp row, render:
- source badge: `Browse`, `Finding`, `HTML`, `PriceCharting`
- validity badge: `✅ Valid` or `⚠️ Excluded`
- warnings:
  - `active overlap`
  - `future date`
  - `missing date`
  - `bundle`
  - `accessory`
  - `wrong variant`
  - `graded`

Example rendering:

```js
if (it.comp_valid) {
  // green badge
} else {
  // amber/red badge with first reject reason
}
```

---

## Step K — add excluded comp section

In `renderAll(d)` after valid sold list:
- if `d.excluded_sold && d.excluded_sold.length`
- render a collapsible section:
  - `Show excluded comps (17)`

This is useful because users can see why medians changed and manually verify your logic.

---

## Step L — chart messaging

If `d.trend_status.available === false`:
- do not render chart
- render message:
  - `Not enough validated sold-date data to show a price trend.`

---

## 5) Verification URL strategy

## Best immediate verification URL
Do **not** use raw View Item pages as proof of sold state.

Instead create a sold-search verification URL:

```python
def _build_sold_verification_url(query, title, item_id=None):
    if item_id:
        return f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(item_id)}&LH_Sold=1&LH_Complete=1"
    title_q = title or query
    return f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(title_q)}&LH_Sold=1&LH_Complete=1"
```

This is not perfect, but it is more honest than treating `itemWebUrl` as a sold archive.

---

## 6) Recommended temporary product policy

Until sold validation is implemented:
- hide chart when `trend.length < 2`
- remove or disable long-range timeline buttons (`1y+`)
- label sold links as `Listing page`, not `Sold item`
- show warning: `Some sold comps may come from buyer-facing eBay listing pages and should be manually verified.`

---

## 7) Test cases to run after implementation

## A. Sold/active overlap rejection
### Query
- `Nintendo Switch OLED`
### Expected
- overlapped item IDs do not contribute to sold median
- overlap count visible in excluded summary

## B. Future sold-date rejection
### Queries
- `Nintendo Switch OLED`
- `Charizard base set`
### Expected
- any comp dated after today excluded
- `trend` uses none of them

## C. Electronics wrong-model rejection
### Query
- `iPhone 13 Pro 256GB unlocked`
### Expected
- `13 Pro Max` excluded
- `12 Pro Max` excluded
- sold median shifts toward true 13 Pro range

## D. Console accessory rejection
### Query
- `Nintendo Switch OLED`
### Expected excluded
- dock
- charger
- case
- shell
- thumb grips
- buttons
- console-only unless query asks for it

## E. Tool parts rejection
### Query
- `DeWalt DCD791 drill`
### Expected excluded
- chuck
- switch label
- housing
- case only
- replacement parts

## F. Card grading separation
### Query
- `Charizard base set`
### Expected
- PSA/BGS/CGC excluded from raw market median unless query says graded
- lots/collections excluded
- Base Set 2 excluded if query asks Base Set

## G. Book format rejection
### Query
- `The Great Gatsby hardcover`
### Expected excluded
- paperback
- guides/casebooks/cookbooks
- multi-book sets unless query requests them

## H. Chart availability rule
### Query
- any query with fewer than 3 validated dated sold comps
### Expected
- chart hidden
- reason shown

## I. URL behavior on frontend
### Expected
- sold comps no longer open raw listing page by default
- verification uses sold-search URL
- raw listing page available only as secondary action

---

## 8) Success criteria

You are done when all are true:
- no future-dated sold comp enters stats
- no active-overlap comp enters stats
- no raw Browse sold result with blank sold date enters stats
- sold list clearly distinguishes valid vs excluded comps
- chart renders only from validated dated sold comps
- users are no longer told that a raw View Item page is proof of a completed sale

---

## 9) Suggested next step after implementation

After backend/frontend changes are in place:
1. rerun live audit on the same six categories
2. compare medians before vs after
3. then perform Prompt 4 for chart/timeline product decisions
