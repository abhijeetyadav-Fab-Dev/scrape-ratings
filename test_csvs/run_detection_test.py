"""Test CSV column detection logic for all formats, matching app.py's exact parsing logic."""
import csv, sys, os, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.abspath(__file__))

test_cases = [
    # Expected: which rows should be detected as MMT (by row content, not by index)
    # test5: row 2 has MMT URL, row 1 and 3 have Booking URLs -> 1 MMT
    # test6: row 3 has MMT URL, row 1 has Booking URL -> 1 MMT
    ("test1_fh_format.csv", 3, "FH ID,hotel names -> all 3 MMT via FH ID"),
    ("test2_hotel_id_format.csv", 3, "Hotel ID,Hotel Name,City -> all 3 MMT via Hotel ID"),
    ("test3_basic_id_format.csv", 3, "ID,Name,City -> all 3 MMT via ID column"),
    ("test4_underscore_format.csv", 3, "Hotel_ID,Hotel_Name,City -> all 3 MMT via Hotel_ID"),
    ("test5_lowercase_format.csv", 1, "id,name,city,url -> 1 MMT via URL, 2 Booking via URL"),
    ("test6_name_only_format.csv", 1, "Name,City,URL -> 1 MMT via URL, 1 Booking via URL"),
]

print("=" * 70)
print("CSV COLUMN DETECTION TEST")
print("=" * 70)

all_pass = True

for csv_name, exp_mmt, desc in test_cases:
    full_path = os.path.join(BASE, csv_name)
    if not os.path.exists(full_path):
        print(f"  FILE NOT FOUND: {csv_name}")
        all_pass = False
        continue

    with open(full_path, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))

    # Find header row
    header_idx = 0
    headers = []
    for i, row in enumerate(rows[:5]):
        lower_row = [c.lower().strip() for c in row]
        if 'name' in lower_row or 'hotel name' in lower_row:
            header_idx = i
            headers = [c.strip() for c in row]
            break
    if not headers:
        headers = [c.strip() for c in rows[0]]

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

    # NEW fix: added 'hotel_id' and 'id' to search terms
    id_idx = find_col('front-end id', 'mmt id', 'fh', 'hotel id', 'hotel_id', 'id')

    items = []
    for row in rows[header_idx + 1:]:
        if name_idx is not None and len(row) <= name_idx:
            continue

        name = row[name_idx].strip() if name_idx is not None and name_idx < len(row) else ''
        city = row[city_idx].strip() if city_idx is not None and city_idx < len(row) else ''
        url = row[link_idx].strip() if link_idx is not None and link_idx < len(row) else ''
        hotel_id = row[id_idx].strip() if id_idx is not None and id_idx < len(row) else ''

        if not name or name.lower() in ('name', 'hotel name', 'hotel'):
            continue

        # Exact app.py parsing logic (order matters):
        if url and 'makemytrip' in url:
            items.append({'name': name, 'source': 'mmt'})
        elif url and 'booking.com' in url:
            items.append({'name': name, 'source': 'booking'})
        elif hotel_id and hotel_id.replace('#', '').strip().isdigit():
            items.append({'name': name, 'source': 'mmt'})
        elif name:
            items.append({'name': name, 'source': 'search'})

    mmt_count = sum(1 for i in items if i['source'] == 'mmt')
    passed = mmt_count == exp_mmt
    if not passed:
        all_pass = False

    status = "PASS" if passed else "FAIL"
    print(f"\n{status} --- {csv_name} ---")
    print(f"  {desc}")
    print(f"  Headers: {headers}")
    print(f"  Detected: name={name_idx}, city={city_idx}, link={link_idx}, id={id_idx}")
    print(f"  MMT: {mmt_count}/{len(items)} items (expected {exp_mmt})")

print(f"\n{'=' * 70}")
if all_pass:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
print('=' * 70)
