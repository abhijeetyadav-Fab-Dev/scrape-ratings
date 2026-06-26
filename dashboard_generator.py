import os
import json
import time
from pathlib import Path

def generate_dashboard_report(results, headers, output_path):
    """
    Generates a premium, interactive HTML match audit dashboard comparing 
    reference hotels and candidate matches side by side.
    """
    
    # Identify column indices from headers
    cand_name_idx = -1
    platform_idx = -1
    cand_address_idx = -1
    similarity_idx = -1
    verdict_idx = -1
    url_idx = -1
    photo_idx = -1
    booking_id_idx = -1
    lat_lng_idx = -1

    for i, h in enumerate(headers):
        hl = h.lower().strip()
        if 'candidate name' in hl: cand_name_idx = i
        elif 'platform' in hl: platform_idx = i
        elif 'candidate address' in hl: cand_address_idx = i
        elif 'similarity' in hl: similarity_idx = i
        elif 'verdict' in hl: verdict_idx = i
        elif 'candidate url' in hl: url_idx = i
        elif 'photo' in hl: photo_idx = i
        elif 'booking' in hl and 'id' in hl: booking_id_idx = i
        elif 'lat' in hl or 'coordinate' in hl: lat_lng_idx = i

    # If headers are not found, assume standard trailing indices
    if cand_name_idx == -1:
        # Assuming last 9 columns
        total_cols = len(headers)
        cand_name_idx = total_cols - 9
        platform_idx = total_cols - 8
        cand_address_idx = total_cols - 7
        similarity_idx = total_cols - 6
        verdict_idx = total_cols - 5
        url_idx = total_cols - 4
        photo_idx = total_cols - 3
        booking_id_idx = total_cols - 2
        lat_lng_idx = total_cols - 1

    # Extract target headers (everything before candidate name)
    target_headers = headers[:cand_name_idx]

    rows_data = []
    stats = {
        'total': len(results),
        'exact': 0,
        'close': 0,
        'no_match': 0,
        'others': 0
    }

    for idx, row in enumerate(results):
        target_info = {}
        for th_idx, th_name in enumerate(target_headers):
            if th_idx < len(row):
                target_info[th_name] = row[th_idx]

        cand_name = row[cand_name_idx] if cand_name_idx < len(row) else ''
        platform = row[platform_idx] if platform_idx < len(row) else ''
        cand_address = row[cand_address_idx] if cand_address_idx < len(row) else ''
        similarity = row[similarity_idx] if similarity_idx < len(row) else ''
        verdict = row[verdict_idx] if verdict_idx < len(row) else ''
        url = row[url_idx] if url_idx < len(row) else ''
        photo = row[photo_idx] if photo_idx < len(row) else ''
        booking_id = row[booking_id_idx] if booking_id_idx < len(row) else ''
        lat_lng = row[lat_lng_idx] if lat_lng_idx < len(row) else ''

        # Tidy up verdict class
        verdict_upper = verdict.upper()
        if 'EXACT' in verdict_upper:
            verdict_class = 'exact'
            stats['exact'] += 1
        elif 'CLOSE' in verdict_upper or 'NEAR' in verdict_upper:
            verdict_class = 'close'
            stats['close'] += 1
        elif 'NO MATCH' in verdict_upper or not cand_name:
            verdict_class = 'no-match'
            stats['no_match'] += 1
        else:
            verdict_class = 'other'
            stats['others'] += 1

        rows_data.append({
            'index': idx + 1,
            'target': target_info,
            'cand_name': cand_name or 'N/A',
            'platform': platform or 'N/A',
            'cand_address': cand_address or 'N/A',
            'similarity': similarity or 'N/A',
            'verdict': verdict or 'No Match Found',
            'verdict_class': verdict_class,
            'url': url,
            'photo': photo or 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=500&auto=format&fit=crop&q=60',
            'booking_id': booking_id,
            'lat_lng': lat_lng
        })

    # Prepare HTML Template with premium CSS and interactive JS
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Match Audit Dashboard — Parallel Hotel Listings</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Plus+Jakarta+Sans:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-main: #0a0e1a;
            --bg-card: rgba(22, 33, 62, 0.7);
            --bg-hover: rgba(30, 41, 75, 0.9);
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-primary: #e94560;
            --accent-sec: #0f3460;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            
            --exact-color: #10b981;
            --close-color: #f5a623;
            --nomatch-color: #ef4444;
            --other-color: #6366f1;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            background-color: var(--bg-main);
            color: var(--text-main);
            font-family: 'Plus Jakarta Sans', sans-serif;
            padding: 2rem;
            min-height: 100vh;
            background-image: radial-gradient(circle at 10% 20%, rgba(233, 69, 96, 0.05) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(99, 102, 241, 0.05) 0%, transparent 40%);
        }}

        header {{
            margin-bottom: 2.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
        }}

        .title-container h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #fff 30%, var(--accent-primary) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }}

        .title-container p {{
            color: var(--text-muted);
            margin-top: 0.25rem;
            font-size: 0.95rem;
        }}

        /* Stats Grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2.5rem;
        }}

        .stat-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            text-align: center;
            backdrop-filter: blur(10px);
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.3);
        }}

        .stat-val {{
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }}

        .stat-label {{
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
        }}

        /* Filter Controls */
        .filters-container {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1rem 1.5rem;
            margin-bottom: 2rem;
            display: flex;
            gap: 1.5rem;
            align-items: center;
            flex-wrap: wrap;
            backdrop-filter: blur(10px);
        }}

        .search-box {{
            flex: 1;
            min-width: 250px;
            position: relative;
        }}

        .search-box input {{
            width: 100%;
            padding: 0.6rem 1rem;
            background: rgba(10, 14, 26, 0.6);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: white;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.2s;
        }}

        .search-box input:focus {{
            border-color: var(--accent-primary);
        }}

        .filter-buttons {{
            display: flex;
            gap: 0.5rem;
        }}

        .filter-btn {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.85rem;
            transition: all 0.2s;
        }}

        .filter-btn:hover, .filter-btn.active {{
            background: var(--accent-primary);
            color: white;
            border-color: var(--accent-primary);
        }}

        /* Match Table */
        .results-table-container {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
            backdrop-filter: blur(10px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}

        th {{
            background: rgba(15, 52, 96, 0.6);
            padding: 1rem 1.25rem;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border-color);
        }}

        td {{
            padding: 1.25rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: top;
        }}

        tr:hover td {{
            background: var(--bg-hover);
        }}

        .hotel-comparison {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }}

        .target-side, .cand-side {{
            padding: 0.5rem;
        }}

        .target-side h4, .cand-side h4 {{
            font-size: 0.8rem;
            text-transform: uppercase;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
            letter-spacing: 0.5px;
        }}

        .hotel-name {{
            font-weight: 700;
            font-size: 1.05rem;
            margin-bottom: 0.25rem;
        }}

        .hotel-address {{
            font-size: 0.85rem;
            color: var(--text-muted);
            line-height: 1.4;
        }}

        .photo-container {{
            width: 70px;
            height: 70px;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }}

        .photo-container img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}

        /* Badges */
        .verdict-badge {{
            display: inline-block;
            padding: 0.35rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .verdict-badge.exact {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--exact-color);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .verdict-badge.close {{
            background: rgba(245, 166, 35, 0.15);
            color: var(--close-color);
            border: 1px solid rgba(245, 166, 35, 0.3);
        }}

        .verdict-badge.no-match {{
            background: rgba(239, 68, 68, 0.15);
            color: var(--nomatch-color);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}

        .verdict-badge.other {{
            background: rgba(99, 102, 241, 0.15);
            color: var(--other-color);
            border: 1px solid rgba(99, 102, 241, 0.3);
        }}

        .platform-tag {{
            display: inline-block;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
            margin-top: 0.5rem;
        }}

        .sim-val {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text-main);
        }}

        .action-link {{
            color: var(--accent-primary);
            text-decoration: none;
            font-size: 0.85rem;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            transition: opacity 0.2s;
        }}

        .action-link:hover {{
            opacity: 0.8;
            text-decoration: underline;
        }}

        .map-btn {{
            background: rgba(99, 102, 241, 0.15);
            color: #818cf8;
            border: 1px solid rgba(99, 102, 241, 0.3);
            font-size: 0.75rem;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-top: 0.5rem;
        }}
    </style>
</head>
<body>

    <header>
        <div class="title-container">
            <h1>Match Audit Dashboard</h1>
            <p>Interactive verification system for crawled listings & parallel directories</p>
        </div>
        <div>
            <span class="platform-tag" style="padding: 0.5rem 1rem; font-size: 0.85rem;">Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}</span>
        </div>
    </header>

    <div class="stats-grid">
        <div class="stat-card" style="border-top: 4px solid var(--text-main);">
            <div class="stat-val">{stats['total']}</div>
            <div class="stat-label">Total Audited</div>
        </div>
        <div class="stat-card" style="border-top: 4px solid var(--exact-color);">
            <div class="stat-val" style="color: var(--exact-color);">{stats['exact']}</div>
            <div class="stat-label">Exact Matches</div>
        </div>
        <div class="stat-card" style="border-top: 4px solid var(--close-color);">
            <div class="stat-val" style="color: var(--close-color);">{stats['close']}</div>
            <div class="stat-label">Close Matches</div>
        </div>
        <div class="stat-card" style="border-top: 4px solid var(--nomatch-color);">
            <div class="stat-val" style="color: var(--nomatch-color);">{stats['no_match']}</div>
            <div class="stat-label">No Matches</div>
        </div>
    </div>

    <div class="filters-container">
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search by name, address, or city..." onkeyup="filterResults()">
        </div>
        <div class="filter-buttons">
            <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
            <button class="filter-btn" onclick="setFilter('exact', this)">Exact</button>
            <button class="filter-btn" onclick="setFilter('close', this)">Close</button>
            <button class="filter-btn" onclick="setFilter('no-match', this)">No Match</button>
        </div>
    </div>

    <div class="results-table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 50px; text-align: center;">#</th>
                    <th style="width: 80px; text-align: center;">Photo</th>
                    <th>Hotel Comparisons (Reference vs Candidate)</th>
                    <th style="width: 120px; text-align: center;">Score</th>
                    <th style="width: 160px; text-align: center;">Verdict</th>
                    <th style="width: 100px; text-align: center;">Action</th>
                </tr>
            </thead>
            <tbody id="resultsTableBody">
"""

    for row in rows_data:
        target_details_html = ""
        for k, v in row['target'].items():
            target_details_html += f"<div><strong>{k}:</strong> {v}</div>"

        map_link_html = ""
        if row['lat_lng'] and ',' in row['lat_lng']:
            map_link_html = f'<a class="map-btn" href="https://www.google.com/maps/search/?api=1&query={row["lat_lng"]}" target="_blank">🗺 View Map</a>'

        html_content += f"""
                <tr class="result-row" data-verdict="{row['verdict_class']}">
                    <td style="text-align: center; font-weight: 700; color: var(--text-muted);">{row['index']}</td>
                    <td style="text-align: center;">
                        <div class="photo-container">
                            <img src="{row['photo']}" alt="Candidate Photo" onerror="this.src='https://images.unsplash.com/photo-1566073771259-6a8506099945?w=500&auto=format&fit=crop&q=60'">
                        </div>
                    </td>
                    <td>
                        <div class="hotel-comparison">
                            <div class="target-side">
                                <h4>Reference Target</h4>
                                <div class="hotel-name">{row['target'].get('Target Name') or row['target'].get('name') or 'N/A'}</div>
                                <div class="hotel-address">
                                    {target_details_html}
                                </div>
                            </div>
                            <div class="cand-side">
                                <h4>Candidate Listing</h4>
                                <div class="hotel-name">{row['cand_name']}</div>
                                <div class="hotel-address">
                                    <div>{row['cand_address']}</div>
                                    <span class="platform-tag">{row['platform']}</span>
                                    {f'<div><small style="color: var(--text-muted);">Booking ID: {row["booking_id"]}</small></div>' if row['booking_id'] else ''}
                                    {map_link_html}
                                </div>
                            </div>
                        </div>
                    </td>
                    <td style="text-align: center; vertical-align: middle;">
                        <div class="sim-val">{row['similarity']}</div>
                    </td>
                    <td style="text-align: center; vertical-align: middle;">
                        <span class="verdict-badge {row['verdict_class']}">{row['verdict']}</span>
                    </td>
                    <td style="text-align: center; vertical-align: middle;">
                        {f'<a class="action-link" href="{row["url"]}" target="_blank">View Live ↗</a>' if row['url'] else '<span style="color: var(--text-muted); font-size: 0.8rem;">No Link</span>'}
                    </td>
                </tr>
"""

    html_content += """
            </tbody>
        </table>
    </div>

    <script>
        let currentFilter = 'all';

        function setFilter(filter, btnEl) {
            currentFilter = filter;
            
            // Toggle active class on buttons
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            btnEl.classList.add('active');
            
            filterResults();
        }

        function filterResults() {
            const searchQuery = document.getElementById('searchInput').value.toLowerCase().strip();
            const rows = document.querySelectorAll('.result-row');
            
            rows.forEach(row => {
                const verdict = row.getAttribute('data-verdict');
                const rowText = row.innerText.toLowerCase();
                
                const matchesFilter = (currentFilter === 'all' || verdict === currentFilter);
                const matchesSearch = (!searchQuery || rowText.includes(searchQuery));
                
                if (matchesFilter && matchesSearch) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }
        
        // Polyfill strip
        if (!String.prototype.strip) {
            String.prototype.strip = function () {
                return this.replace(/^\s+|\s+$/g, '');
            };
        }
    </script>
</body>
</html>
"""

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        return True
    except Exception as e:
        print(f"Failed to generate dashboard report: {e}")
        return False

def generate_ratings_report(csv_path, html_path):
    """
    Generates a premium, interactive HTML ratings summary dashboard.
    """
    import csv
    import os
    import time
    if not os.path.exists(csv_path):
        return False
        
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            rows = list(reader)
    except Exception as e:
        print(f"Failed to read CSV for ratings report: {e}")
        return False
        
    rating_idx = -1
    reviews_idx = -1
    source_idx = -1
    fail_idx = -1
    name_idx = -1
    city_idx = -1
    url_idx = -1
    
    for i, h in enumerate(headers):
        hl = h.lower()
        if 'rating' in hl: rating_idx = i
        elif 'review' in hl: reviews_idx = i
        elif 'source' in hl: source_idx = i
        elif 'fail' in hl or 'reason' in hl: fail_idx = i
        elif 'name' in hl: name_idx = i
        elif 'city' in hl: city_idx = i
        elif 'url' in hl: url_idx = i
        
    if name_idx == -1: name_idx = 0
    if city_idx == -1: city_idx = 1
    if url_idx == -1: url_idx = 2
    
    stats = {
        'total': len(rows),
        'scraped': 0,
        'failed': 0,
        'high_rated': 0
    }
    
    table_rows_html = ""
    for idx, r in enumerate(rows):
        name = r[name_idx] if name_idx < len(r) else ''
        city = r[city_idx] if city_idx < len(r) else ''
        url = r[url_idx] if url_idx < len(r) else ''
        
        rating = r[rating_idx] if rating_idx != -1 and rating_idx < len(r) else 'N/A'
        reviews = r[reviews_idx] if reviews_idx != -1 and reviews_idx < len(r) else '0'
        source = r[source_idx] if source_idx != -1 and source_idx < len(r) else 'Unknown'
        fail_reason = r[fail_idx] if fail_idx != -1 and fail_idx < len(r) else ''
        
        is_success = rating and rating not in ('N/A', '', 'ERROR', 'CANCELLED')
        if is_success:
            stats['scraped'] += 1
            try:
                rating_val = float(rating.split('/')[0]) if '/' in rating else float(rating)
                if '/' in rating and '5' in rating.split('/')[1]:
                    rating_val = rating_val * 2
                if rating_val >= 8.0:
                    stats['high_rated'] += 1
            except:
                pass
        else:
            stats['failed'] += 1
            
        badge_class = 'exact' if is_success else 'no-match'
        verdict = 'SUCCESS' if is_success else ('FAILED: ' + fail_reason if fail_reason else 'FAILED')
        
        table_rows_html += f"""
            <tr class="result-row" data-verdict="{ 'exact' if is_success else 'no-match' }">
                <td style="text-align: center; font-weight: 700; color: var(--text-muted);">{idx + 1}</td>
                <td>
                    <div class="hotel-name">{name}</div>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">{city}</div>
                </td>
                <td style="text-align: center; vertical-align: middle;">
                    <span class="platform-tag">{source}</span>
                </td>
                <td style="text-align: center; vertical-align: middle;">
                    <div class="sim-val" style="color: {'var(--exact-color)' if is_success else 'var(--text-muted)'}">{rating or 'N/A'}</div>
                </td>
                <td style="text-align: center; vertical-align: middle;">
                    <div>{reviews or '0'}</div>
                </td>
                <td style="text-align: center; vertical-align: middle;">
                    <span class="verdict-badge {badge_class}">{verdict}</span>
                </td>
                <td style="text-align: center; vertical-align: middle;">
                    {f'<a class="action-link" href="{url}" target="_blank">View Live ↗</a>' if url else '<span style="color: var(--text-muted); font-size: 0.85rem;">No URL</span>'}
                </td>
            </tr>
        """
        
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ratings Audit Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Plus+Jakarta+Sans:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-main: #0a0e1a;
            --bg-card: rgba(22, 33, 62, 0.7);
            --bg-hover: rgba(30, 41, 75, 0.9);
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-primary: #e94560;
            --accent-sec: #0f3460;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            
            --exact-color: #10b981;
            --close-color: #f5a623;
            --nomatch-color: #ef4444;
            --other-color: #6366f1;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            background-color: var(--bg-main);
            color: var(--text-main);
            font-family: 'Plus Jakarta Sans', sans-serif;
            padding: 2rem;
            min-height: 100vh;
            background-image: radial-gradient(circle at 10% 20%, rgba(233, 69, 96, 0.05) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(99, 102, 241, 0.05) 0%, transparent 40%);
        }}

        header {{
            margin-bottom: 2.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
        }}

        .title-container h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #fff 30%, var(--accent-primary) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }}

        .title-container p {{
            color: var(--text-muted);
            margin-top: 0.25rem;
            font-size: 0.95rem;
        }}

        /* Stats Grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2.5rem;
        }}

        .stat-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            text-align: center;
            backdrop-filter: blur(10px);
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.3);
        }}

        .stat-val {{
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }}

        .stat-label {{
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
        }}

        /* Filter Controls */
        .filters-container {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1rem 1.5rem;
            margin-bottom: 2rem;
            display: flex;
            gap: 1.5rem;
            align-items: center;
            flex-wrap: wrap;
            backdrop-filter: blur(10px);
        }}

        .search-box {{
            flex: 1;
            min-width: 250px;
            position: relative;
        }}

        .search-box input {{
            width: 100%;
            padding: 0.6rem 1rem;
            background: rgba(10, 14, 26, 0.6);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: white;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.2s;
        }}

        .search-box input:focus {{
            border-color: var(--accent-primary);
        }}

        .filter-buttons {{
            display: flex;
            gap: 0.5rem;
        }}

        .filter-btn {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.85rem;
            transition: all 0.2s;
        }}

        .filter-btn:hover, .filter-btn.active {{
            background: var(--accent-primary);
            color: white;
            border-color: var(--accent-primary);
        }}

        /* Match Table */
        .results-table-container {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
            backdrop-filter: blur(10px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}

        th {{
            background: rgba(15, 52, 96, 0.6);
            padding: 1rem 1.25rem;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border-color);
        }}

        td {{
            padding: 1.25rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }}

        tr:hover td {{
            background: var(--bg-hover);
        }}

        .hotel-name {{
            font-weight: 700;
            font-size: 1.05rem;
            margin-bottom: 0.25rem;
        }}

        /* Badges */
        .verdict-badge {{
            display: inline-block;
            padding: 0.35rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .verdict-badge.exact {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--exact-color);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .verdict-badge.no-match {{
            background: rgba(239, 68, 68, 0.15);
            color: var(--nomatch-color);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}

        .platform-tag {{
            display: inline-block;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
        }}

        .sim-val {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text-main);
        }}

        .action-link {{
            color: var(--accent-primary);
            text-decoration: none;
            font-size: 0.85rem;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            transition: opacity 0.2s;
        }}

        .action-link:hover {{
            opacity: 0.8;
            text-decoration: underline;
        }}
    </style>
</head>
<body>

    <header>
        <div class="title-container">
            <h1>Ratings Audit Dashboard</h1>
            <p>Summary of scraped property ratings and reviews across platforms</p>
        </div>
        <div>
            <span class="platform-tag" style="padding: 0.5rem 1rem; font-size: 0.85rem;">Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}</span>
        </div>
    </header>

    <div class="stats-grid">
        <div class="stat-card" style="border-top: 4px solid var(--text-main);">
            <div class="stat-val">{stats['total']}</div>
            <div class="stat-label">Total Hotels</div>
        </div>
        <div class="stat-card" style="border-top: 4px solid var(--exact-color);">
            <div class="stat-val" style="color: var(--exact-color);">{stats['scraped']}</div>
            <div class="stat-label">Scraped successfully</div>
        </div>
        <div class="stat-card" style="border-top: 4px solid var(--close-color);">
            <div class="stat-val" style="color: var(--close-color);">{stats['high_rated']}</div>
            <div class="stat-label">Highly Rated (>= 8.0)</div>
        </div>
        <div class="stat-card" style="border-top: 4px solid var(--nomatch-color);">
            <div class="stat-val" style="color: var(--nomatch-color);">{stats['failed']}</div>
            <div class="stat-label">Scraping Failures</div>
        </div>
    </div>

    <div class="filters-container">
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search by name or city..." onkeyup="filterResults()">
        </div>
        <div class="filter-buttons">
            <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
            <button class="filter-btn" onclick="setFilter('exact', this)">Success</button>
            <button class="filter-btn" onclick="setFilter('no-match', this)">Failed</button>
        </div>
    </div>

    <div class="results-table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 50px; text-align: center;">#</th>
                    <th>Hotel Name & Location</th>
                    <th style="width: 150px; text-align: center;">Platform</th>
                    <th style="width: 120px; text-align: center;">Rating</th>
                    <th style="width: 120px; text-align: center;">Reviews</th>
                    <th style="width: 160px; text-align: center;">Status</th>
                    <th style="width: 100px; text-align: center;">Action</th>
                </tr>
            </thead>
            <tbody id="resultsTableBody">
                {table_rows_html}
            </tbody>
        </table>
    </div>

    <script>
        let currentFilter = 'all';

        function setFilter(filter, btnEl) {
            currentFilter = filter;
            
            // Toggle active class on buttons
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            btnEl.classList.add('active');
            
            filterResults();
        }

        function filterResults() {
            const searchQuery = document.getElementById('searchInput').value.toLowerCase().trim();
            const rows = document.querySelectorAll('.result-row');
            
            rows.forEach(row => {
                const verdict = row.getAttribute('data-verdict');
                const rowText = row.innerText.toLowerCase();
                
                const matchesFilter = (currentFilter === 'all' || verdict === currentFilter);
                const matchesSearch = (!searchQuery || rowText.includes(searchQuery));
                
                if (matchesFilter && matchesSearch) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }
    </script>
</body>
</html>
"""
    try:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        return True
    except Exception as e:
        print(f"Failed to generate ratings dashboard: {e}")
        return False
