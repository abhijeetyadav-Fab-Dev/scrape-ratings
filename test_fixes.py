"""
Self-contained test script to validate scraper fixes.
Does NOT require PyQt6 - tests the core extraction logic directly.
Uses only ASCII characters for Windows cp1252 compatibility.
"""
import re, sys, os, csv, io, json, time
from pathlib import Path

# Copy of the critical _extract_rating_review_count function (the one we fixed)
def extract_ratings(content):
    """Duplicate of app.py's _extract_rating_review_count to test without PyQt6."""
    rating, review_count = None, None

    # Rating patterns (on a 1-10 scale)
    rating_patterns = [
        r'\"ratingValue\"[\s:]*\"?(\d+\.?\d*)',
        r'ratingValue[\s:>]+(\d+\.?\d*)',
        r'Scored\s+(\d+\.?\d*)',
        r'\"score\"[\s:]+(\d+\.?\d*)',
        r'review_score[\s:=]+(\d+\.?\d*)',
        r'\"averageScore\"[\s:]+(\d+\.?\d*)',
        r'(\d+\.\d)\s*/\s*10',
        r'\"reviewScore\">(\d+\.?\d*)<',
        r'<strong[^>]*>(\d+\.\d)</strong>',
    ]
    for pat in rating_patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if 1 <= val <= 10:
                    rating = str(val)
                    break
            except ValueError:
                continue

    # Review count patterns
    count_patterns = [
        r'\"reviewCount\"[\s:]*\"?(\d+)',
        r'\"numberOfReviews\"[\s:]+(\d+)',
        r'([\d,]+)\s*reviews?',
        r'([\d,]+)\s*ratings?',
        r'\"reviewCount\">(\d+)<',
    ]
    for pat in count_patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            raw_count = m.group(1).replace(",", "")
            try:
                if int(raw_count) > 0:
                    review_count = raw_count
                    break
            except ValueError:
                review_count = None

    return rating, review_count


# TEST RUNNER
passed = 0
failed = 0

print("=" * 70)
print("SCRAPER FIX VALIDATION TEST SUITE")
print("=" * 70)

# Test 0: sys.stdout encoding
print(f"[INFO] stdout encoding: {sys.stdout.encoding}")

# Test 1: Good old patterns verify that escaped patterns match
print("\n--- Test 1: Regex patterns match correctly ---")
# The OLD broken patterns had \\d (which in raw strings means literal \\d)
# The NEW fixed patterns have \d which matches digits
# We verify the new patterns work:

test_html_1 = '{"ratingValue": "8.5", "reviewCount": 342}'
rating, count = extract_ratings(test_html_1)
if rating == "8.5":
    print(f"  [PASS] ratingValue extracted: {rating}")
    passed += 1
else:
    print(f"  [FAIL] ratingValue extraction: expected 8.5, got {rating}")
    failed += 1
if count == "342":
    print(f"  [PASS] reviewCount extracted: {count}")
    passed += 1
else:
    print(f"  [FAIL] reviewCount extraction: expected 342, got {count}")
    failed += 1

# Test 2: Various rating formats
print("\n--- Test 2: Multiple rating format matching ---")

tests = [
    # (name, html, expected_rating, expected_count)
    ("averageScore JSON",       '"averageScore": 7.8', "7.8", None),
    ("review_score attr",       'review_score = 9.2', "9.2", None),
    ("Scored text",             'Scored 8.2', "8.2", None),
    ("X/10 format",             '8.5 / 10', "8.5", None),
    ("reviewCount JSON",        '"reviewCount": "150"', None, "150"),
    ("numberOfReviews JSON",    '"numberOfReviews": 200', None, "200"),
    ("X reviews text",          '342 reviews', None, "342"),
    ("X ratings text (comma)",  '1,234 ratings', None, "1234"),
    ("strong tag rating",       '<strong>8.9</strong>', "8.9", None),
    ("reviewScore HTML attr",   '"reviewScore">9.1<', "9.1", None),
    ("full Booking page",       'Scored 8.7<br>256 reviews', "8.7", "256"),
    ("ratingValue with spaces", ' "ratingValue" : "9.4" ', "9.4", None),
    ("ratings keyword",         '850 ratings', None, "850"),
]

for label, html, exp_rating, exp_count in tests:
    rating, count = extract_ratings(html)
    ok = True
    issues = []
    if exp_rating is not None and rating != exp_rating:
        ok = False
        issues.append(f"rating: expected {exp_rating}, got {rating}")
    if exp_rating is None and rating is not None:
        ok = False
        issues.append(f"rating: expected None, got {rating}")
    if exp_count is not None and count != exp_count:
        ok = False
        issues.append(f"count: expected {exp_count}, got {count}")
    if exp_count is None and count is not None:
        ok = False
        issues.append(f"count: expected None, got {count}")
    
    if ok:
        print(f"  [PASS] {label}: rating={rating}, reviews={count}")
        passed += 1
    else:
        print(f"  [FAIL] {label}: {'; '.join(issues)}")
        failed += 1

# Test 3: Out-of-range values should NOT match
print("\n--- Test 3: Out-of-range values rejected ---")

edge_cases = [
    ("rating too high (11.0)", '{"ratingValue": "11.0"}', None, None),
    ("rating zero", '{"ratingValue": "0.0"}', None, None),
    ("reviewCount zero", '{"reviewCount": "0"}', None, None),
    ("reviewCount negative", '{"reviewCount": "-5"}', None, None),
]

for label, html, exp_rating, exp_count in edge_cases:
    rating, count = extract_ratings(html)
    ok = True
    issues = []
    if rating != exp_rating:
        ok = False
        issues.append(f"rating: expected {exp_rating}, got {rating}")
    if count != exp_count:
        ok = False
        issues.append(f"count: expected {exp_count}, got {count}")
    
    if ok:
        print(f"  [PASS] {label}")
        passed += 1
    else:
        print(f"  [FAIL] {label}: {'; '.join(issues)}")
        failed += 1

# Test 4: CSV column detection
print("\n--- Test 4: CSV column detection ---")

csv_data = io.StringIO("""FH ID,Hotel Name,City,Address,Zipcode,Latitude,Longitude,Link,B.com ID
32775,Hotel Ridz,Kolkata,Address,700136,22.62,88.45,https://www.booking.com/hotel/test.html,8062182
32808,Hotel SS,Kanpur,Address,208024,26.49,80.28,https://www.makemytrip.com/hotels/hotel-details/?hotelId=ABC123,4735846
""")
rows = list(csv.reader(csv_data))
headers = rows[0]
lower_headers = [h.lower() for h in headers]

def find_col(*names):
    for n in names:
        if len(n) <= 3:
            for i, h in enumerate(lower_headers):
                if re.search(r'(?<![a-z])' + re.escape(n) + r'(?![a-z])', h):
                    return i
        else:
            for i, h in enumerate(lower_headers):
                if n in h:
                    return i
    return None

name_idx = find_col('name', 'hotel')
city_idx = find_col('city', 'location')
link_idx = find_col('mmt', 'link', 'url')
id_idx = find_col('front-end id', 'mmt id', 'fh', 'hotel id', 'hotel_id')

print(f"  Headers: {headers}")
print(f"  name_idx={name_idx} (expect 1)")
print(f"  city_idx={city_idx} (expect 2)")
print(f"  link_idx={link_idx} (expect 7)")
print(f"  id_idx={id_idx} (expect 0)")

all_ok = True
if name_idx != 1:
    print(f"  [FAIL] name_idx: expected 1, got {name_idx}")
    all_ok = False
if city_idx != 2:
    print(f"  [FAIL] city_idx: expected 2, got {city_idx}")
    all_ok = False
if link_idx != 7:
    print(f"  [FAIL] link_idx: expected 7, got {link_idx}")
    all_ok = False
if id_idx != 0:
    print(f"  [FAIL] id_idx: expected 0, got {id_idx}")
    all_ok = False

if all_ok:
    print(f"  [PASS] CSV column detection correct")
    passed += 1
else:
    print(f"  [FAIL] CSV column detection incorrect")
    failed += 1

# Test 5: Clean booking URL
print("\n--- Test 5: clean_booking_url ---")

def clean_booking_url(url):
    match = re.match(r'(https://www\.booking\.com/hotel/[^?;]+)', url)
    return match.group(1) if match else url

test_urls = [
    ("https://www.booking.com/hotel/in/foo.en-gb.html?aid=123&label=abc",
     "https://www.booking.com/hotel/in/foo.en-gb.html"),
    ("https://www.booking.com/hotel/in/bar.html",
     "https://www.booking.com/hotel/in/bar.html"),
    ("https://www.booking.com/hotel/in/baz?param=1",
     "https://www.booking.com/hotel/in/baz"),
    ("not-a-booking-url",
     "not-a-booking-url"),
]

for url, expected in test_urls:
    result = clean_booking_url(url)
    if result == expected:
        print(f"  [PASS] {url[:55]} -> {result}")
        passed += 1
    else:
        print(f"  [FAIL] expected {expected}, got {result}")
        failed += 1

# Test 6: Booking.com links are classified correctly (not as MMT)
print("\n--- Test 6: URL source classification ---")

def classify_source(url, source_from_csv=""):
    if source_from_csv == 'mmt' or 'makemytrip' in (url or ''):
        return 'MMT'
    elif url and ('booking.com' in url or 'http' in url):
        return 'Booking.com'
    return 'unknown'

test_links = [
    ("https://www.booking.com/hotel/in/test.html", False, "Booking.com"),
    ("https://www.makemytrip.com/hotels/detail.html?hotelId=123", False, "MMT"),
    ("", False, "unknown"),
    ("https://www.booking.com/hotel/in/test2.html", "", "Booking.com"),  # URL determines source, not CSV
]

for url, is_mmt_csv, expected in test_links:
    src_csv = 'mmt' if is_mmt_csv else ''
    result = classify_source(url, src_csv)
    if result == expected:
        print(f"  [PASS] {expected}: {url[:55]}")
        passed += 1
    else:
        print(f"  [FAIL] expected {expected}, got {result}")
        failed += 1

# SUMMARY
print("\n" + "=" * 70)
print(f"FINAL: {passed}/{passed+failed} tests passed")
print("=" * 70)
if failed == 0:
    print("ALL TESTS PASSED -- regex fixes, CSV detection, URL cleaning working correctly.")
else:
    print(f"WARNING: {failed} test(s) failed")
print()
