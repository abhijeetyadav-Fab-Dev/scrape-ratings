"""Fix the worker's section_map to include missing compound prefixes."""

with open("universal_scraper.py", "r", encoding="utf-8") as f:
    content = f.read()

old = '''                section_map = {
                    "res": "reservations", "prop": "property",
                    "rev": "reviews", "fin": "financial",
                    "promo": "promotions",
                    "exp_ci": "insights",
                    "htl_ci": "insights",
                    "goi_rpt": "reports",
                    "dash": "dashboard",      # Booking.com Dashboard / Home
                    "rate": "rates",          # Booking.com Rates & Availability
                    "boost": "boost",         # Booking.com Boost Performance
                    "inb": "inbox",           # Booking.com Inbox / Messages
                    "anl": "analytics",       # Booking.com Analytics
                    "mmt": "reservations",    # fallback for mmt_ prefixed keys
                    "goi": "reservations",    # fallback for goi_ prefixed keys
                    "agd": "reservations",    # fallback for agd_ prefixed keys
                    "exp": "reservations",    # fallback for exp_ prefixed keys
                    "htl": "reservations",    # fallback for htl_ prefixed keys
                }'''

new = '''                section_map = {
                    "res": "reservations", "prop": "property",
                    "rev": "reviews", "fin": "financial",
                    "promo": "promotions",
                    # Source-specific section prefixes (compound 2-part keys)
                    "exp_ci": "insights",
                    "htl_ci": "insights",
                    "goi_rpt": "reports",
                    "mmt_rev": "reviews",          # MMT Reviews
                    "mmt_settlement": "financial",  # MMT Financial
                    "goi_rev": "reviews",           # Goibibo Reviews
                    "goi_settlement": "financial",  # Goibibo Financial
                    "agd_rev": "reviews",           # Agoda Reviews
                    "agd_prop": "property",         # Agoda Property
                    "exp_rev": "reviews",           # Expedia Reviews
                    "exp_prop": "property",         # Expedia Property
                    "htl_rev": "reviews",           # Hotels.com Reviews
                    "htl_prop": "property",         # Hotels.com Property
                    # Booking.com section prefixes (single-word keys)
                    "dash": "dashboard",
                    "rate": "rates",
                    "boost": "boost",
                    "inb": "inbox",
                    "anl": "analytics",
                    # Fallback simple prefixes -> "reservations"
                    "mmt": "reservations",
                    "goi": "reservations",
                    "agd": "reservations",
                    "exp": "reservations",
                    "htl": "reservations",
                }'''

count = content.count(old)
print(f"Found {count} occurrence(s)")
if count >= 1:
    content = content.replace(old, new, 1)
    with open("universal_scraper.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Replaced successfully!")
else:
    idx = content.find('section_map = {\n                    "res": "reservations", "prop": "property",')
    print(f"Alternative find result: {idx}")
    if idx >= 0:
        print("Context around match:")
        print(repr(content[idx:idx+700]))
    else:
        print("Could not find the section_map anywhere!")
