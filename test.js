
        // Main Connection mode management
        let isLocalConnected = false;

        function toggleConnectionMode() {
            const val = document.getElementById('app-conn-mode').value;
            const dot = document.getElementById('engine-pulse-dot');
            const lbl = document.getElementById('engine-status-lbl');
            const input = document.getElementById('app-local-url');

            if (val === 'local') {
                input.classList.remove('hidden');
                pingLocalEngine();
            } else {
                input.classList.add('hidden');
                isLocalConnected = false;
                dot.className = "h-2.5 w-2.5 rounded-full bg-zinc-600";
                lbl.textContent = "Offline Mode";
                lbl.className = "text-[10px] uppercase font-bold text-zinc-500";
            }
        }

        async function pingLocalEngine() {
            const url = document.getElementById('app-local-url').value.trim();
            const dot = document.getElementById('engine-pulse-dot');
            const lbl = document.getElementById('engine-status-lbl');

            try {
                const res = await fetch(`${url}/api/ratings/session_status`, { mode: 'cors' });
                if (res.ok) {
                    isLocalConnected = true;
                    dot.className = "h-2.5 w-2.5 rounded-full bg-emerald-500 animate-pulse";
                    lbl.textContent = "Engine Connected";
                    lbl.className = "text-[10px] uppercase font-bold text-emerald-400";
                } else {
                    throw new Error("Bad status");
                }
            } catch(e) {
                isLocalConnected = false;
                dot.className = "h-2.5 w-2.5 rounded-full bg-rose-600";
                lbl.textContent = "Engine Unavailable";
                lbl.className = "text-[10px] uppercase font-bold text-rose-500";
            }
        }

        function getBaseUrl() {
            if (isLocalConnected) {
                return document.getElementById('app-local-url').value.trim();
            }
            return '';
        }

        // Main Tab switching
        function switchMainTab(tabName) {
            document.querySelectorAll('.main-pane').forEach(p => p.classList.add('hidden'));
            document.querySelectorAll('[id^="main-tab-"]').forEach(btn => {
                btn.className = "px-6 py-3.5 text-xs font-bold uppercase tracking-wider border-r border-[#2d3748] text-zinc-400 hover:text-white hover:bg-[#1a2232] transition flex items-center gap-2";
            });

            document.getElementById('pane-' + tabName).classList.remove('hidden');
            const activeBtn = document.getElementById('main-tab-' + tabName);
            if (activeBtn) {
                activeBtn.className = "px-6 py-3.5 text-xs font-bold uppercase tracking-wider border-r border-[#2d3748] text-white bg-[#1e293b] transition flex items-center gap-2";
            }
        }

        // ── TAB 1: RATINGS SCRAPER JS ───────────────────────────────
        let activeRatingsPlatform = 'quick';
        let ratingsActiveInterval = null;
        let ratingsActiveSessionId = null;

        const PLATFORM_INFOS = {
            'quick': {
                'title': 'Quick Search',
                'body': 'Auto-detect: paste any hotel link (Booking, MMT, Agoda, Expedia) or just a hotel name.',
                'placeholder': 'Paste hotel link, name, or ID (auto-detects platform)...',
                'bulk': 'Paste links or hotel names here (one per line)...',
                'rules_title': 'Auto-detection rules',
                'rules': `
                    <div>✓ booking.com/hotel/... → Booking.com</div>
                    <div>✓ makemytrip.com/hotelid=... → MMT</div>
                    <div>✓ goibibo.com/... → Goibibo</div>
                    <div>✓ agoda.com/... → Agoda</div>
                    <div>✓ expedia.com/... → Expedia</div>
                    <div>✓ Numeric FH ID → MMT</div>
                    <div>✓ Plain text → search by name</div>
                `
            },
            'booking': {
                'title': 'Booking.com',
                'body': 'Scrapes Booking.com hotel ratings. Runs in headless mode — no login needed. Accepts URLs or hotel names.',
                'placeholder': 'Paste Booking.com URL or hotel name...',
                'bulk': 'Paste Booking.com links or hotel names (one per line)...',
                'rules_title': 'How it works',
                'rules': `
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Headless — no browser window opens</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>No login required</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Accepts: booking.com/hotel/... URLs or hotel names</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Rating scale: /10</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Can search by hotel name + city if URL redirects</div>
                `
            },
            'mmt': {
                'title': 'MMT (MakeMyTrip)',
                'body': 'Scrapes MMT hotel ratings. Uses visible browser with saved login session. Accepts FH IDs or MMT URLs.',
                'placeholder': 'Paste MMT hotel URL or FH ID (e.g. 32775)...',
                'bulk': 'Paste MMT links or FH IDs (one per line)...',
                'rules_title': 'How it works',
                'rules': `
                    <div><i class="fa-solid fa-triangle-exclamation text-amber-500 mr-1.5"></i>Visible browser — Chrome opens to load MMT pages</div>
                    <div><i class="fa-solid fa-triangle-exclamation text-amber-500 mr-1.5"></i>Requires an active MMT login session</div>
                    <div id="mmt-session-detail-active"><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Checking session status...</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Accepts: MMT FH IDs (e.g. 32775) or full MMT URLs</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Rating scale: /5</div>
                `
            },
            'goibibo': {
                'title': 'Goibibo',
                'body': 'Scrapes Goibibo hotel ratings. Uses Chrome remote debugging — no login needed. Accepts Goibibo URLs or hotel names.',
                'placeholder': 'Paste Goibibo URL or hotel name...',
                'bulk': 'Paste Goibibo links or hotel names (one per line)...',
                'rules_title': 'How it works',
                'rules': `
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Runs in Chrome remote debugging mode to avoid protocol blocking</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>No login required</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Accepts: goibibo.com/hotels/... URLs or hotel names</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Rating scale: /5</div>
                `
            },
            'agoda': {
                'title': 'Agoda',
                'body': 'Scrapes Agoda hotel ratings. Runs in headless mode — no login needed. Accepts Agoda URLs or hotel names.',
                'placeholder': 'Paste Agoda URL or hotel name...',
                'bulk': 'Paste Agoda links or hotel names (one per line)...',
                'rules_title': 'How it works',
                'rules': `
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Headless — no browser window opens</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>No login required</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Accepts: Agoda URLs or hotel names</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Rating scale: /10</div>
                    <div><i class="fa-solid fa-circle-info text-sky-500 mr-1.5"></i>Basic implementation — may need adjustments for Agoda's page structure</div>
                `
            },
            'expedia': {
                'title': 'Expedia',
                'body': 'Scrapes Expedia hotel ratings. Runs in headless mode — no login needed. Accepts Expedia URLs or hotel names.',
                'placeholder': 'Paste Expedia URL or hotel name...',
                'bulk': 'Paste Expedia links or hotel names (one per line)...',
                'rules_title': 'How it works',
                'rules': `
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Headless — no browser window opens</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>No login required</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Accepts: Expedia URLs or hotel names</div>
                    <div><i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Rating scale: /10</div>
                    <div><i class="fa-solid fa-circle-info text-sky-500 mr-1.5"></i>Basic implementation — may need adjustments for Expedia's page structure</div>
                `
            }
        };

        function switchRatingsSubTab(platformKey) {
            activeRatingsPlatform = platformKey;
            
            // Toggle sub-tab active class
            document.querySelectorAll('.ratings-sub-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');

            // Update title and descriptions
            const info = PLATFORM_INFOS[platformKey] || PLATFORM_INFOS['quick'];
            document.getElementById('ratings-desc-title').textContent = info.title;
            document.getElementById('ratings-desc-body').textContent = info.body;
            document.getElementById('ratings-quick-input').placeholder = info.placeholder;
            document.getElementById('ratings-bulk-input').placeholder = info.bulk;

            // Update rules title & content
            document.getElementById('ratings-rules-title').textContent = info.rules_title;
            document.getElementById('ratings-rules-content').innerHTML = info.rules;

            if (platformKey === 'mmt') {
                checkMMTSession();
            }
        }

        function toggleFrontendLinksPanel() {
            const el = document.getElementById('ratings-fl-subcard');
            el.classList.toggle('hidden');
        }

        function buildRatingsFrontendLinks() {
            const id = document.getElementById('ratings-fl-id').value.trim();
            const name = document.getElementById('ratings-fl-name').value.trim();
            if (!id && !name) {
                alert("Please fill in Hotel ID or Hotel Name first!");
                return;
            }
            const res = document.getElementById('ratings-fl-result');
            res.classList.remove('hidden');
            res.innerHTML = '';
            if (id) {
                res.innerHTML += `<div><strong>MMT:</strong> https://www.makemytrip.com/hotels/hotel-details.html?hotelId=${id}</div>`;
                res.innerHTML += `<div><strong>Goibibo:</strong> https://www.goibibo.com/hotels/hotel-details.html?hotelId=${id}</div>`;
            }
            if (name) {
                res.innerHTML += `<div><strong>Booking:</strong> https://www.booking.com/searchresults.html?ss=${encodeURIComponent(name)}</div>`;
                res.innerHTML += `<div><strong>Agoda:</strong> https://www.agoda.com/pages/agoda/default/DestinationSearchResult.aspx?asq=${encodeURIComponent(name)}</div>`;
            }
        }

        function logRatingsTerminal(msg, isErr=false, isSuccess=false) {
            const term = document.getElementById('ratings-terminal-logs');
            const d = document.createElement('div');
            d.textContent = msg;
            if (isErr) d.className = 'text-rose-400 font-semibold';
            else if (isSuccess) d.className = 'text-emerald-400 font-bold';
            term.appendChild(d);
            term.scrollTop = term.scrollHeight;
        }

        // CSV Sample download
        function downloadRatingsSample() {
            const headers = "name,url,city,source\n";
            const row1 = "FabHotel Grand Olive,https://www.booking.com/hotel/in/grand-olive.html,Delhi,booking\n";
            const row2 = "FabHotel Silver Lake,,Noida,mmt\n";
            const csvContent = "data:text/csv;charset=utf-8," + encodeURIComponent(headers + row1 + row2);
            
            const link = document.createElement("a");
            link.setAttribute("href", csvContent);
            link.setAttribute("download", "ratings_import_sample.csv");
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            logRatingsTerminal("> Downloaded ratings CSV sample sheet.");
        }

        let parsedCSVRows = [];
        function handleRatingsCSV(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(e) {
                const text = e.target.result;
                const rows = parseCSVText(text);
                parsedCSVRows = rows.map(r => {
                    return {
                        name: r.name || r.hotel_name || r.hotelName || '',
                        url: r.url || r.link || '',
                        city: r.city || '',
                        source: r.source || 'quick'
                    };
                });
                logRatingsTerminal(`> Loaded CSV file: ${file.name} (${parsedCSVRows.length} hotels parsed). Click Start to scrape.`);
            };
            reader.readAsText(file);
        }

        async function checkMMTSession() {
            if (!isLocalConnected) {
                const lbl = document.getElementById('mmt-session-label');
                lbl.textContent = "Offline Mode — Ratings will run in simulation mode";
                lbl.className = "text-xs text-zinc-550 italic";
                return;
            }
            try {
                const res = await fetch(`${getBaseUrl()}/api/ratings/session_status`);
                const data = await res.json();
                const lbl = document.getElementById('mmt-session-label');
                const detail = document.getElementById('mmt-session-detail-active');
                
                if (data.mmt_active) {
                    lbl.textContent = "MMT session active";
                    lbl.className = "text-xs text-emerald-400 font-bold";
                    if (detail) {
                        detail.innerHTML = `<i class="fa-solid fa-check text-emerald-500 mr-1.5"></i>Session active`;
                    }
                } else {
                    lbl.textContent = "MMT: No session";
                    lbl.className = "text-xs text-rose-400 font-bold";
                    if (detail) {
                        detail.innerHTML = `<i class="fa-solid fa-triangle-exclamation text-amber-500 mr-1.5"></i>No active session — click 'Login to MMT'`;
                    }
                }
            } catch(e) {
                console.error("Failed session status lookup", e);
            }
        }

        async function loginMMT() {
            if (!isLocalConnected) {
                alert("This action requires a local running engine session. Switching to Local Engine Mode first is recommended.");
                return;
            }
            logRatingsTerminal("> Opening MMT headed login browser window. Log in on your desktop...");
            try {
                const res = await fetch(`${getBaseUrl()}/api/ratings/login_mmt`, { method: 'POST' });
                const data = await res.json();
                logRatingsTerminal(`> ${data.message}`);
            } catch(e) {
                logRatingsTerminal(`> ERROR starting MMT login: ${e.message}`, true);
            }
        }

        async function searchSingleRating() {
            const val = document.getElementById('ratings-quick-input').value.trim();
            if (!val) {
                alert("Please enter a hotel link or name first!");
                return;
            }
            const item = {
                name: val.includes('http') ? '' : val,
                url: val.includes('http') ? val : '',
                source: activeRatingsPlatform
            };
            runRatingsJob([item]);
        }

        async function triggerRatingsStart() {
            let items = [];
            const textVal = document.getElementById('ratings-bulk-input').value.trim();
            if (textVal) {
                const lines = textVal.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                items = lines.map(line => {
                    return {
                        name: line.includes('http') ? '' : line,
                        url: line.includes('http') ? line : '',
                        source: activeRatingsPlatform
                    };
                });
            } else if (parsedCSVRows.length > 0) {
                items = parsedCSVRows;
            } else {
                alert("Please enter URLs/Names in the textarea or upload a CSV first!");
                return;
            }

            runRatingsJob(items);
        }

        async function runRatingsJob(items) {
            if (!isLocalConnected) {
                runRatingsJobSimulation(items);
                return;
            }

            const payload = {
                items: items,
                workers: parseInt(document.getElementById('ratings-concurrency-workers').value) || 10
            };

            logRatingsTerminal(`> Triggering ratings scrape job for ${items.length} properties...`);
            document.getElementById('ratings-progress-wrapper').classList.remove('hidden');

            try {
                const res = await fetch(`${getBaseUrl()}/api/ratings/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok) {
                    ratingsActiveSessionId = data.session_id;
                    document.getElementById('ratings-run-btn').disabled = true;
                    document.getElementById('ratings-stop-worker-btn').disabled = false;
                    document.getElementById('ratings-download-csv-btn').disabled = true;
                    
                    ratingsActiveInterval = setInterval(pollRatingsStatus, 1000);
                    logRatingsTerminal(`> Job session started: ${ratingsActiveSessionId}`, false, true);
                } else {
                    logRatingsTerminal(`> Failed to start ratings scraper: ${data.error}`, true);
                }
            } catch(e) {
                logRatingsTerminal(`> Network error starting ratings job: ${e.message}`, true);
            }
        }

        function runRatingsJobSimulation(items) {
            logRatingsTerminal("> Launching Client-Side Scraper Simulation Mode...");
            document.getElementById('ratings-progress-wrapper').classList.remove('hidden');
            document.getElementById('ratings-run-btn').disabled = true;
            document.getElementById('ratings-stop-worker-btn').disabled = false;

            let idx = 0;
            const workers = 2;
            const total = items.length;

            const simInterval = setInterval(() => {
                if (idx >= total) {
                    clearInterval(simInterval);
                    logRatingsTerminal("> [Simulation Complete] Scrape pipeline completed successfully. Resolving client spreadsheet output...", false, true);
                    document.getElementById('ratings-run-btn').disabled = false;
                    document.getElementById('ratings-stop-worker-btn').disabled = true;
                    document.getElementById('ratings-download-csv-btn').disabled = false;
                    return;
                }

                const item = items[idx];
                const pct = Math.round(((idx+1) / total) * 100);
                document.getElementById('ratings-live-percent').textContent = `${pct}%`;
                document.getElementById('ratings-live-progress-fill').style.width = `${pct}%`;
                document.getElementById('ratings-live-status').textContent = `Resolving index links for: ${item.name || item.url}...`;

                const rating = (4.0 + Math.random() * 0.9).toFixed(1);
                const count = Math.floor(100 + Math.random() * 900);
                logRatingsTerminal(`> Scraped ${item.name || 'Property'} (OTA match found) → Rating: ${rating} (${count} reviews)`, false, true);

                idx++;
            }, 800);
        }

        async function pollRatingsStatus() {
            if (!ratingsActiveSessionId) return;
            try {
                const res = await fetch(`${getBaseUrl()}/api/ratings/status/${ratingsActiveSessionId}`);
                const data = await res.json();
                if (res.ok) {
                    const val = data.progress_val || 0;
                    const max = data.progress_max || 1;
                    const pct = Math.round((val / max) * 100);
                    
                    document.getElementById('ratings-live-percent').textContent = `${pct}%`;
                    document.getElementById('ratings-live-progress-fill').style.width = `${pct}%`;
                    document.getElementById('ratings-live-status').textContent = data.status_text || 'Running...';
                    
                    const term = document.getElementById('ratings-terminal-logs');
                    term.innerHTML = '';
                    data.logs.forEach(l => {
                        const d = document.createElement('div');
                        d.textContent = l;
                        if (l.includes('ERROR') || l.includes('❌')) d.className = 'text-rose-400';
                        else if (l.includes('✅') || l.includes('Complete')) d.className = 'text-emerald-400 font-bold';
                        term.appendChild(d);
                    });
                    term.scrollTop = term.scrollHeight;

                    if (data.finished) {
                        logRatingsTerminal("> Ratings scrape job completed successfully!", false, true);
                        clearInterval(ratingsActiveInterval);
                        
                        document.getElementById('ratings-run-btn').disabled = false;
                        document.getElementById('ratings-stop-worker-btn').disabled = true;
                        document.getElementById('ratings-download-csv-btn').disabled = false;
                    }
                }
            } catch(e) {
                console.error(e);
            }
        }

        async function stopRatingsScrape() {
            if (!ratingsActiveSessionId) return;
            try {
                await fetch(`${getBaseUrl()}/api/ratings/stop/${ratingsActiveSessionId}`, { method: 'POST' });
                logRatingsTerminal("> Termination request submitted to server worker.");
            } catch(e) {
                logRatingsTerminal(`> Cancel error: ${e.message}`, true);
            }
        }

        function downloadRatingsCSV() {
            if (!isLocalConnected) {
                alert("Simulated spreadsheet saved locally inside downloads folder.");
                return;
            }
            window.location.href = `${getBaseUrl()}/api/ratings/download/${ratingsActiveSessionId}`;
        }

        function clearRatingsInputs() {
            document.getElementById('ratings-quick-input').value = '';
            document.getElementById('ratings-bulk-input').value = '';
            parsedCSVRows = [];
            document.getElementById('ratings-terminal-logs').innerHTML = '<div class="text-zinc-650">> Console cleared.</div>';
            document.getElementById('ratings-progress-wrapper').classList.add('hidden');
        }

        function openSettingsDialog() {
            alert("Settings Dialog: Default user-agents, timeout delays, and SQLite credentials configurations are loaded from system config.");
        }


        // ── TAB 2: GOD MODE JS ─────────────────────────────────────
        let activeGodModeTab = 'scanner';
        let gmFields = [];
        let generatedGMBLinksList = [];

        function switchGodModeSubTab(tabName) {
            activeGodModeTab = tabName;
            document.querySelectorAll('.godmode-sub-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');

            document.getElementById('godmode-sub-scanner').style.display = tabName === 'scanner' ? 'block' : 'none';
            document.getElementById('godmode-sub-builder').style.display = tabName === 'builder' ? 'grid' : 'none';
            document.getElementById('godmode-sub-finder').style.display = tabName === 'finder' ? 'grid' : 'none';
        }

        function logGodModeTerminal(msg, isErr=false) {
            const term = document.getElementById('godmode-terminal-logs');
            const d = document.createElement('div');
            d.textContent = msg;
            if (isErr) d.className = 'text-rose-400 font-semibold';
            term.appendChild(d);
            term.scrollTop = term.scrollHeight;
        }

        async function triggerGodModeScan() {
            const url = document.getElementById('godmode-scan-url').value.trim();
            if (!url) {
                alert("Please enter a valid page URL to scan!");
                return;
            }

            logGodModeTerminal(`> Initiating Chrome headless context...`);
            logGodModeTerminal(`> Fetching coordinates and loading target layout: ${url}`);

            if (!isLocalConnected) {
                // simulated scan results
                setTimeout(() => {
                    logGodModeTerminal(`> [Offline Sim] Detected layout parameters for URL.`);
                    const container = document.getElementById('gm-fields-list');
                    container.innerHTML = '';
                    gmFields = [
                        { label: 'Rating Node', value: 'div.rating-value (e.g. 4.5)' },
                        { label: 'Review Count Node', value: 'span.review-count (e.g. 1,024 reviews)' },
                        { label: 'Room Price Node', value: 'div.price-box (e.g. Rs. 1,786)' }
                    ];
                    gmFields.forEach(f => {
                        const d = document.createElement('div');
                        d.className = 'flex items-center justify-between p-1.5 rounded hover:bg-zinc-800/60 select-none cursor-pointer';
                        d.onclick = () => d.classList.toggle('bg-blue-600/20');
                        d.innerHTML = `<span><strong>${f.label}:</strong> ${f.value}</span>`;
                        container.appendChild(d);
                    });
                }, 1000);
                return;
            }

            try {
                const res = await fetch(`${getBaseUrl()}/api/godmode/scan`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                const data = await res.json();
                if (res.ok) {
                    logGodModeTerminal(`> Scan completed. Auto-detected page title: "${data.title || 'Page'}"`);
                    
                    const container = document.getElementById('gm-fields-list');
                    container.innerHTML = '';
                    gmFields = [];

                    if (data.ratings && data.ratings.length > 0) {
                        data.ratings.forEach((r, idx) => {
                            const f = { label: `Detected Rating #${idx+1}`, value: `${r.rating} (${r.count} reviews)` };
                            gmFields.push(f);
                        });
                    }
                    if (data.tables && data.tables.length > 0) {
                        data.tables.forEach((t, idx) => {
                            const f = { label: `Table #${idx+1}`, value: `${t.row_count} rows, cols: ${t.headers.join(',')}` };
                            gmFields.push(f);
                        });
                    }
                    if (data.lists && data.lists.length > 0) {
                        data.lists.forEach((l, idx) => {
                            const f = { label: `List #${idx+1}`, value: `${l.item_count} items (Sample: ${l.sample[0]})` };
                            gmFields.push(f);
                        });
                    }

                    if (gmFields.length === 0) {
                        container.innerHTML = '<div class="text-zinc-655 italic">No structured data blocks detected. Enter custom CSS selector below.</div>';
                    } else {
                        gmFields.forEach((f, idx) => {
                            const d = document.createElement('div');
                            d.className = 'flex items-center justify-between p-1.5 rounded hover:bg-zinc-800/60 select-none cursor-pointer';
                            d.onclick = () => d.classList.toggle('bg-blue-600/20');
                            d.innerHTML = `<span><strong>${f.label}:</strong> ${f.value}</span>`;
                            container.appendChild(d);
                        });
                    }
                } else {
                    logGodModeTerminal(`> ERROR during page scan: ${data.error}`, true);
                }
            } catch(e) {
                logGodModeTerminal(`> Network execution error: ${e.message}`, true);
            }
        }

        function removeSelectedGMField() {
            const list = document.getElementById('gm-fields-list');
            const selected = list.querySelectorAll('.bg-blue-600\\/20');
            selected.forEach(el => el.remove());
            logGodModeTerminal("> Removed selected DOM elements from active target list.");
        }

        function addCustomGMField() {
            const sel = document.getElementById('gm-custom-selector').value.trim();
            if (!sel) return;
            const container = document.getElementById('gm-fields-list');
            if (container.querySelector('.italic')) {
                container.innerHTML = '';
            }
            const d = document.createElement('div');
            d.className = 'flex items-center justify-between p-1.5 rounded hover:bg-zinc-800/60 select-none cursor-pointer';
            d.onclick = () => d.classList.toggle('bg-blue-600/20');
            d.innerHTML = `<span><strong>Custom Selector:</strong> ${sel}</span>`;
            container.appendChild(d);
            document.getElementById('gm-custom-selector').value = '';
            logGodModeTerminal(`> Added custom CSS target field: "${sel}"`);
        }

        function clearGodModeLogs() {
            document.getElementById('godmode-terminal-logs').innerHTML = '<div class="text-zinc-650">> Logs cleared.</div>';
        }

        function runGMBulkuris() {
            const name = document.getElementById('gmb-hotel-name').value.trim();
            const city = document.getElementById('gmb-city').value.trim();
            const id = document.getElementById('gmb-hotel-id').value.trim();
            const existUrl = document.getElementById('gmb-exist-url').value.trim();

            if (!name && !id) {
                alert("Please fill in Hotel Name or Hotel ID!");
                return;
            }

            const tbody = document.getElementById('gmb-urls-table');
            tbody.innerHTML = '';
            generatedGMBLinksList = [];

            const addLink = (platform, link) => {
                generatedGMBLinksList.push(link);
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="py-2.5 px-3 font-bold text-zinc-300 border-b border-zinc-900">${platform}</td>
                    <td class="py-2.5 px-3 border-b border-zinc-900 break-all"><a href="${link}" target="_blank" class="text-cyan-400 hover:underline">${link}</a></td>
                `;
                tbody.appendChild(tr);
            };

            if (id) {
                addLink('MakeMyTrip', `https://www.makemytrip.com/hotels/hotel-details.html?hotelId=${id}`);
                addLink('Goibibo', `https://www.goibibo.com/hotels/hotel-details.html?hotelId=${id}`);
            }
            if (name) {
                const searchStr = city ? `${name} ${city}` : name;
                addLink('Booking.com', `https://www.booking.com/searchresults.html?ss=${encodeURIComponent(searchStr)}`);
                addLink('Agoda', `https://www.agoda.com/pages/agoda/default/DestinationSearchResult.aspx?asq=${encodeURIComponent(searchStr)}`);
                addLink('Expedia', `https://www.expedia.com/Hotel-Search?destination=${encodeURIComponent(searchStr)}`);
            }
        }

        }

        function copyGeneratedGMBLinks() {
            if (generatedGMBLinksList.length === 0) return;
            navigator.clipboard.writeText(generatedGMBLinksList.join('\n'));
            alert("All generated links copied to clipboard!");
        }

        // ── GOD MODE LINK BUILDER (BULK) ──
        let gmbBulkRows = [];
        let gmbBulkResults = [];
        let gmbIsRunning = false;

        function logGMBTerminal(msg, isErr=false) {
            const term = document.querySelector('#godmode-sub-builder .terminal-box');
            if (!term) return;
            const d = document.createElement('div');
            d.textContent = msg;
            if (isErr) d.className = 'text-rose-400 font-semibold';
            term.appendChild(d);
            term.scrollTop = term.scrollHeight;
        }

        function downloadGMLinkSample() {
            const headers = "Hotel Name,City,FHID,URL\n";
            const row1 = "FabHotel Raj Villa,Indore,1234,http://booking.com/...\n";
            const row2 = "FabHotel The Corporate,Mumbai,,\n";
            const csvContent = "data:text/csv;charset=utf-8," + encodeURIComponent(headers + row1 + row2);
            const link = document.createElement("a");
            link.setAttribute("href", csvContent);
            link.setAttribute("download", "sample_link_builder.csv");
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            logGMBTerminal("> Downloaded link builder sample CSV.");
        }

        function handleGMBCSV(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(e) {
                const text = e.target.result;
                const rows = parseCSVText(text);
                gmbBulkRows = rows.map(r => ({
                    name: r["Hotel Name"] || r.name || r.hotel_name || '',
                    city: r.City || r.city || '',
                    hotel_id: r.FHID || r.fhid || r.hotel_id || '',
                    url: r.URL || r.url || ''
                }));
                
                const lines = gmbBulkRows.map(r => `${r.name}, ${r.city}${r.hotel_id ? ', ' + r.hotel_id : ''}`);
                document.getElementById('gmb-bulk-text').value = lines.join('\n');
                logGMBTerminal(`> Loaded CSV: ${file.name} (${gmbBulkRows.length} properties parsed).`);
            };
            reader.readAsText(file);
        }

        function runGMBulkLinkBuilder() {
            const text = document.getElementById('gmb-bulk-text').value.trim();
            if (!text) {
                alert("Please paste data or load a CSV first!");
                return;
            }

            const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
            gmbBulkResults = [];
            gmbIsRunning = true;

            document.getElementById('gmb-start-btn').disabled = true;
            document.getElementById('gmb-stop-btn').disabled = false;
            document.getElementById('gmb-download-btn').disabled = true;

            const term = document.querySelector('#godmode-sub-builder .terminal-box');
            term.innerHTML = '<div>> Starting Bulk Link Builder process...</div>';

            let idx = 0;
            function processNext() {
                if (!gmbIsRunning) return;
                if (idx >= lines.length) {
                    logGMBTerminal(`> Finished! Built links for ${gmbBulkResults.length} properties.`, false);
                    document.getElementById('gmb-start-btn').disabled = false;
                    document.getElementById('gmb-stop-btn').disabled = true;
                    document.getElementById('gmb-download-btn').disabled = false;
                    return;
                }

                const line = lines[idx];
                const parts = line.split(',').map(p => p.trim());
                const name = parts[0] || 'Unknown';
                const city = parts[1] || '';
                const hotel_id = parts[2] || '';
                const url = parts[3] || '';

                logGMBTerminal(`> Formatting index references for: ${name}...`);

                // Formulate links
                const query = city ? `${name} ${city}` : name;
                const queryEncoded = encodeURIComponent(query);
                
                const bookingLink = `https://www.booking.com/searchresults.en-gb.html?ss=${queryEncoded}`;
                const mmtLink = hotel_id ? `https://www.makemytrip.com/hotels/hotel-details/?hotelId=${hotel_id}` : `https://www.makemytrip.com/hotels/?search=${encodeURIComponent(name)}`;
                const agodaLink = `https://www.agoda.com/search?text=${encodeURIComponent(name)}`;
                const expediaLink = `https://www.expedia.com/hotels/search?text=${encodeURIComponent(name)}`;
                const goibiboLink = `https://www.goibibo.com/hotels/find-hotels-in-india/?searchText=${encodeURIComponent(name)}`;

                gmbBulkResults.push({
                    "Hotel Name": name,
                    "City": city,
                    "FHID": hotel_id,
                    "URL": url,
                    "Booking Link": bookingLink,
                    "MMT Link": mmtLink,
                    "Agoda Link": agodaLink,
                    "Expedia Link": expediaLink,
                    "Goibibo Link": goibiboLink
                });

                idx++;
                setTimeout(processNext, 150);
            }
            processNext();
        }

        function stopGMBulkLinkBuilder() {
            gmbIsRunning = false;
            logGMBTerminal("> Process stopped by user.");
            document.getElementById('gmb-start-btn').disabled = false;
            document.getElementById('gmb-stop-btn').disabled = true;
        }

        function downloadGMBulkCSV() {
            if (gmbBulkResults.length === 0) return;
            const headers = ["Hotel Name", "City", "FHID", "URL", "Booking Link", "MMT Link", "Agoda Link", "Expedia Link", "Goibibo Link"];
            let csvContent = headers.join(",") + "\n";
            gmbBulkResults.forEach(r => {
                const row = headers.map(h => `"${(r[h] || '').replace(/"/g, '""')}"`);
                csvContent += row.join(",") + "\n";
            });
            const link = document.createElement("a");
            link.setAttribute("href", "data:text/csv;charset=utf-8," + encodeURIComponent(csvContent));
            link.setAttribute("download", "bulk_built_links.csv");
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        }

        function clearGMBBulk() {
            document.getElementById('gmb-bulk-text').value = '';
            gmbBulkResults = [];
            document.querySelector('#godmode-sub-builder .terminal-box').innerHTML = '<div>> Idle. Ready to batch generate search indexes...</div>';
            document.getElementById('gmb-download-btn').disabled = true;
        }

        // ── GOD MODE PARALLEL FINDER (BULK) ──
        let gmfBulkRows = [];
        let gmfActiveSessionId = null;
        let gmfActiveInterval = null;
        let gmfBulkResults = [];
        let gmfIsRunning = false;

        function logGMFTerminal(msg, isErr=false) {
            const term = document.querySelector('#godmode-sub-finder .terminal-box');
            if (!term) return;
            const d = document.createElement('div');
            d.textContent = msg;
            if (isErr) d.className = 'text-rose-400 font-semibold';
            term.appendChild(d);
            term.scrollTop = term.scrollHeight;
        }

        function downloadGMParallelSample() {
            const headers = "Hotel Name,City\n";
            const row1 = "FabHotel Raj Villa,Indore\n";
            const row2 = "FabHotel The Corporate,Mumbai\n";
            const csvContent = "data:text/csv;charset=utf-8," + encodeURIComponent(headers + row1 + row2);
            const link = document.createElement("a");
            link.setAttribute("href", csvContent);
            link.setAttribute("download", "sample_parallel_finder.csv");
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            logGMFTerminal("> Downloaded parallel finder sample CSV.");
        }

        function handleGMFCSV(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(e) {
                const text = e.target.result;
                const rows = parseCSVText(text);
                gmfBulkRows = rows.map(r => ({
                    name: r["Hotel Name"] || r.name || r.hotel_name || '',
                    city: r.City || r.city || ''
                }));
                const lines = gmfBulkRows.map(r => `${r.name}, ${r.city}`);
                document.getElementById('gmf-bulk-text').value = lines.join('\n');
                logGMFTerminal(`> Loaded CSV: ${file.name} (${gmfBulkRows.length} properties parsed).`);
            };
            reader.readAsText(file);
        }

        async function runGMBulkParallel() {
            const text = document.getElementById('gmf-bulk-text').value.trim();
            if (!text) {
                alert("Please paste data or load a CSV first!");
                return;
            }

            const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
            const items = lines.map(line => {
                const parts = line.split(',');
                return { name: parts[0] || '', city: parts[1] || '' };
            });

            document.getElementById('gmf-start-btn').disabled = true;
            document.getElementById('gmf-stop-btn').disabled = false;
            document.getElementById('gmf-download-btn').disabled = true;

            if (!isLocalConnected) {
                // Offline Simulation Mode
                logGMFTerminal("> [Simulation] Starting Bulk Parallel search pipeline...");
                gmfIsRunning = true;
                gmfBulkResults = [];
                let idx = 0;
                
                function processNextSim() {
                    if (!gmfIsRunning) return;
                    if (idx >= items.length) {
                        logGMFTerminal(`> [Simulation Complete] Scanned ${gmfBulkResults.length} hotels. Excel report resolved.`, false);
                        document.getElementById('gmf-start-btn').disabled = false;
                        document.getElementById('gmf-stop-btn').disabled = true;
                        document.getElementById('gmf-download-btn').disabled = false;
                        return;
                    }
                    const item = items[idx];
                    logGMFTerminal(`> Scanning platforms for Target: ${item.name} (${item.city})...`);
                    logGMFTerminal(`  [BOOKING] Match: ${item.name} (98% similarity)`);
                    logGMFTerminal(`  [MMT] Match: ${item.name} (95% similarity)`);
                    logGMFTerminal(`  [AGODA] Match: ${item.name} (99% similarity)`);
                    
                    gmfBulkResults.push({
                        "Hotel Name": item.name,
                        "City": item.city,
                        "Booking Match": item.name,
                        "Booking URL": `https://www.booking.com/searchresults.html?ss=${encodeURIComponent(item.name)}`,
                        "Booking Similarity": "98%",
                        "MMT Match": item.name,
                        "MMT URL": `https://www.makemytrip.com/hotels/?search=${encodeURIComponent(item.name)}`,
                        "MMT Similarity": "95%",
                        "Agoda Match": item.name,
                        "Agoda URL": `https://www.agoda.com/search?text=${encodeURIComponent(item.name)}`,
                        "Agoda Similarity": "99%"
                    });
                    
                    idx++;
                    setTimeout(processNextSim, 1000);
                }
                processNextSim();
                return;
            }

            logGMFTerminal(`> Dispatching parallel worker task to local engine...`);

            try {
                const res = await fetch(`${getBaseUrl()}/api/godmode/bulk_parallel/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: items, platforms: ['booking', 'mmt', 'agoda', 'expedia'] })
                });
                const data = await res.json();
                if (res.ok) {
                    gmfActiveSessionId = data.session_id;
                    gmfActiveInterval = setInterval(pollGMFStatus, 1500);
                } else {
                    logGMFTerminal(`> Error starting job: ${data.error}`, true);
                    document.getElementById('gmf-start-btn').disabled = false;
                    document.getElementById('gmf-stop-btn').disabled = true;
                }
            } catch (e) {
                logGMFTerminal(`> Connection error: ${e.message}`, true);
                document.getElementById('gmf-start-btn').disabled = false;
                document.getElementById('gmf-stop-btn').disabled = true;
            }
        }

        async function pollGMFStatus() {
            if (!gmfActiveSessionId) return;
            try {
                const res = await fetch(`${getBaseUrl()}/api/godmode/bulk_parallel/status/${gmfActiveSessionId}`);
                const data = await res.json();
                if (res.ok) {
                    const term = document.querySelector('#godmode-sub-finder .terminal-box');
                    term.innerHTML = '';
                    data.logs.forEach(l => {
                        const d = document.createElement('div');
                        d.textContent = l;
                        if (l.includes('Error') || l.includes('🛑')) d.className = 'text-rose-400';
                        else if (l.includes('✅')) d.className = 'text-emerald-400 font-bold';
                        term.appendChild(d);
                    });
                    term.scrollTop = term.scrollHeight;

                    if (data.finished) {
                        clearInterval(gmfActiveInterval);
                        logGMFTerminal("> Bulk parallel search finished!", false);
                        document.getElementById('gmf-start-btn').disabled = false;
                        document.getElementById('gmf-stop-btn').disabled = true;
                        document.getElementById('gmf-download-btn').disabled = false;
                    }
                }
            } catch (e) {
                console.error(e);
            }
        }

        async function stopGMBulkParallel() {
            if (!isLocalConnected) {
                gmfIsRunning = false;
                logGMFTerminal("> Simulation stopped by user.");
                document.getElementById('gmf-start-btn').disabled = false;
                document.getElementById('gmf-stop-btn').disabled = true;
                return;
            }
            if (!gmfActiveSessionId) return;
            try {
                await fetch(`${getBaseUrl()}/api/godmode/bulk_parallel/stop/${gmfActiveSessionId}`, { method: 'POST' });
            } catch (e) {
                console.error(e);
            }
        }

        function downloadGMFBulkCSV() {
            if (!isLocalConnected) {
                if (gmfBulkResults.length === 0) return;
                const headers = ["Hotel Name", "City", "Booking Match", "Booking URL", "Booking Similarity", "MMT Match", "MMT URL", "MMT Similarity", "Agoda Match", "Agoda URL", "Agoda Similarity"];
                let csvContent = headers.join(",") + "\n";
                gmfBulkResults.forEach(r => {
                    const row = headers.map(h => `"${(r[h] || '').replace(/"/g, '""')}"`);
                    csvContent += row.join(",") + "\n";
                });
                const link = document.createElement("a");
                link.setAttribute("href", "data:text/csv;charset=utf-8," + encodeURIComponent(csvContent));
                link.setAttribute("download", "bulk_parallel_listings.csv");
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                return;
            }
            if (!gmfActiveSessionId) return;
            window.location.href = `${getBaseUrl()}/api/godmode/bulk_parallel/download/${gmfActiveSessionId}`;
        }

        function clearGMFBulk() {
            document.getElementById('gmf-bulk-text').value = '';
            document.querySelector('#godmode-sub-finder .terminal-box').innerHTML = '<div>> Idle. Ready to batch resolve mapping links...</div>';
            document.getElementById('gmf-download-btn').disabled = true;
            gmfBulkResults = [];
        }

        // ── GOD MODE PARALLEL FINDER (SINGLE SEARCH) ──
        async function runSingleParallelFinder() {
            const name = document.getElementById('gmf-name').value.trim();
            const city = document.getElementById('gmf-city').value.trim();
            if (!name) {
                alert("Please enter a hotel name first!");
                return;
            }

            const checkedPlatforms = Array.from(document.querySelectorAll('input[name="gmf-platforms"]:checked')).map(cb => cb.value);
            if (checkedPlatforms.length === 0) {
                alert("Please select at least one platform to search!");
                return;
            }

            const tbody = document.getElementById('gmf-candidates-tbody');
            tbody.innerHTML = '<tr><td colspan="6" class="py-6 text-center text-zinc-400 font-semibold"><i class="fa-solid fa-spinner fa-spin mr-1.5"></i>Searching platforms in headless browser context...</td></tr>';
            
            document.getElementById('gmf-single-btn').disabled = true;
            document.getElementById('gmf-single-stop-btn').disabled = false;

            if (!isLocalConnected) {
                // Offline Simulation Mode
                setTimeout(() => {
                    tbody.innerHTML = '';
                    const simCandidates = [];
                    checkedPlatforms.forEach(plat => {
                        simCandidates.push({
                            name: name,
                            platform: plat,
                            location: city ? `${city}, India` : 'India',
                            similarity: 98,
                            url: `https://www.${plat}.com/search`,
                            photo_match: "95% match"
                        });
                    });
                    
                    simCandidates.forEach(c => {
                        const tr = document.createElement('tr');
                        tr.className = 'border-b border-zinc-900 hover:bg-zinc-800/10 transition';
                        tr.innerHTML = `
                            <td class="py-2.5 px-3 font-semibold text-white">${c.name}</td>
                            <td class="py-2.5 px-3 text-zinc-400 font-bold uppercase">${c.platform}</td>
                            <td class="py-2.5 px-3 text-zinc-300 max-w-xs truncate">${c.location}</td>
                            <td class="py-2.5 px-3 text-emerald-400 font-bold">${c.similarity}%</td>
                            <td class="py-2.5 px-3 text-zinc-500">${c.photo_match}</td>
                            <td class="py-2.5 px-3 text-right">
                                <a href="${c.url}" target="_blank" class="text-cyan-400 hover:underline font-bold">View Link</a>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                    document.getElementById('gmf-single-btn').disabled = false;
                    document.getElementById('gmf-single-stop-btn').disabled = true;
                }, 1500);
                return;
            }

            try {
                const res = await fetch(`${getBaseUrl()}/api/godmode/parallel_finder`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name, city: city, platforms: checkedPlatforms })
                });
                const data = await res.json();
                
                document.getElementById('gmf-single-btn').disabled = false;
                document.getElementById('gmf-single-stop-btn').disabled = true;

                if (res.ok) {
                    tbody.innerHTML = '';
                    const list = data.candidates || [];
                    if (list.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="6" class="py-6 text-center text-zinc-550 italic">No duplicate listing candidates found.</td></tr>';
                        return;
                    }
                    list.forEach(c => {
                        const tr = document.createElement('tr');
                        tr.className = 'border-b border-zinc-900 hover:bg-zinc-800/10 transition';
                        tr.innerHTML = `
                            <td class="py-2.5 px-3 font-semibold text-white">${c.name}</td>
                            <td class="py-2.5 px-3 text-zinc-400 font-bold uppercase">${c.platform}</td>
                            <td class="py-2.5 px-3 text-zinc-300 max-w-xs truncate">${c.location}</td>
                            <td class="py-2.5 px-3 text-emerald-400 font-bold">${c.similarity}%</td>
                            <td class="py-2.5 px-3 text-zinc-500">${c.photo_match}</td>
                            <td class="py-2.5 px-3 text-right">
                                <a href="${c.url}" target="_blank" class="text-cyan-400 hover:underline font-bold">View Link</a>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                } else {
                    tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-rose-400 font-semibold">Search failed: ${data.error}</td></tr>`;
                }
            } catch (e) {
                document.getElementById('gmf-single-btn').disabled = false;
                document.getElementById('gmf-single-stop-btn').disabled = true;
                tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-rose-400 font-semibold">Connection failed: ${e.message}</td></tr>`;
            }
        }

        function stopSingleParallelFinder() {
            document.getElementById('gmf-single-btn').disabled = false;
            document.getElementById('gmf-single-stop-btn').disabled = true;
            document.getElementById('gmf-candidates-tbody').innerHTML = '<tr><td colspan="6" class="py-6 text-center text-zinc-650 italic">Search cancelled.</td></tr>';
        }

        async function lookupCoordinates() {
            const name = document.getElementById('gmf-name').value.trim();
            const city = document.getElementById('gmf-city').value.trim();
            if (!city) {
                alert("Please enter a City first!");
                return;
            }
            try {
                const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(name + ' ' + city)}`);
                const data = await res.json();
                if (data && data.length > 0) {
                    document.getElementById('gmf-latlong').value = `${parseFloat(data[0].lat).toFixed(4)}, ${parseFloat(data[0].lon).toFixed(4)}`;
                } else {
                    const resCity = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(city)}`);
                    const dataCity = await resCity.json();
                    if (dataCity && dataCity.length > 0) {
                        document.getElementById('gmf-latlong').value = `${parseFloat(dataCity[0].lat).toFixed(4)}, ${parseFloat(dataCity[0].lon).toFixed(4)}`;
                    } else {
                        alert("Coordinates not found. Please enter manually.");
                    }
                }
            } catch (e) {
                alert("Lookup failed. Please enter coordinates manually.");
            }
        }


        // ── TAB 3: UNIVERSAL SCRAPER JS ─────────────────────────────
        let univSources = {};
        let activeUnivSubTab = 'config';
        let univActiveSessionId = null;
        let univActiveInterval = null;
        
        const DYNAMIC_UNIV_FIELDS = {
            'booking': {
                'group': 'Home',
                'fields': [
                    { 'key': 'dashboard', 'label': 'Home Dashboard (Sub-Tab)' },
                    { 'key': 'occupancy', 'label': 'Occupancy' },
                    { 'key': 'rev_ytd', 'label': 'Revenue YTD' },
                    { 'key': 'adr', 'label': 'Average Daily Rate' },
                    { 'key': 'revpar', 'label': 'RevPAR' }
                ]
            },
            'mmt': {
                'group': 'Reservations / Bookings',
                'fields': [
                    { 'key': 'booking_id', 'label': 'Booking ID' },
                    { 'key': 'guest_name', 'label': 'Guest Name' },
                    { 'key': 'checkin', 'label': 'Check-in Date' },
                    { 'key': 'checkout', 'label': 'Check-out Date' },
                    { 'key': 'room_type', 'label': 'Room Type' }
                ]
            },
            'goibibo': {
                'group': 'Reservations / Bookings',
                'fields': [
                    { 'key': 'booking_id', 'label': 'Booking ID' },
                    { 'key': 'guest_name', 'label': 'Guest Name' },
                    { 'key': 'checkin', 'label': 'Check-in Date' },
                    { 'key': 'checkout', 'label': 'Check-out Date' },
                    { 'key': 'room_type', 'label': 'Room Type' }
                ]
            },
            'async': {
                'group': 'URL_Content',
                'fields': [
                    { 'key': 'source_url', 'label': 'Source URL' },
                    { 'key': 'page_title', 'label': 'Page Title' },
                    { 'key': 'scrape_status', 'label': 'Scrape Status' },
                    { 'key': 'timestamp', 'label': 'Timestamp' }
                ]
            },
            'hotels': {
                'group': 'Reservations / Bookings',
                'fields': [
                    { 'key': 'booking_id', 'label': 'Booking ID' },
                    { 'key': 'guest_name', 'label': 'Guest Name' },
                    { 'key': 'checkin', 'label': 'Check-in Date' },
                    { 'key': 'checkout', 'label': 'Check-out Date' },
                    { 'key': 'room_type', 'label': 'Room Type' }
                ]
            }
        };

        function switchUniversalSubTab(tabName) {
            activeUnivSubTab = tabName;
            document.querySelectorAll('.universal-sub-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');

            document.getElementById('universal-sub-config').style.display = tabName === 'config' ? 'block' : 'none';
            document.getElementById('universal-sub-history').style.display = tabName === 'history' ? 'block' : 'none';
        }

        async function loadUnivSources() {
            handleUnivSourceChange();
        }

        function handleUnivSourceChange() {
            const key = document.getElementById('univ-source-select').value;
            const container = document.getElementById('univ-fields-container');
            const status = document.getElementById('univ-session-status');
            container.innerHTML = '';

            if (!key) {
                container.innerHTML = '<div class="text-zinc-655 italic text-xs">Choose a Data Source above to see available fields...</div>';
                status.textContent = "Not logged in";
                status.className = "text-xs text-zinc-500 font-semibold";
                return;
            }

            // Mock login state display
            if (key === 'booking') {
                status.textContent = "✓ Session active";
                status.className = "text-xs text-emerald-400 font-semibold";
            } else {
                status.textContent = "Not logged in";
                status.className = "text-xs text-zinc-550 font-semibold";
            }

            const data = DYNAMIC_UNIV_FIELDS[key];
            if (data) {
                const box = document.createElement('div');
                box.className = 'group-box';
                box.innerHTML = `<span class="group-box-title">${data.group}</span>`;
                
                const grid = document.createElement('div');
                grid.className = 'grid grid-cols-1 md:grid-cols-2 gap-3.5 mt-2';
                
                data.fields.forEach(f => {
                    const label = document.createElement('label');
                    label.className = 'flex items-start space-x-2.5 p-2 rounded hover:bg-zinc-800/40 cursor-pointer select-none';
                    label.innerHTML = `
                        <input type="checkbox" name="univ-fields" value="${f.key}" class="w-4 h-4 rounded text-blue-600 bg-zinc-900 border-zinc-700 mt-0.5">
                        <div>
                            <span class="text-xs font-semibold text-zinc-300 block">${f.label}</span>
                        </div>
                    `;
                    grid.appendChild(label);
                });
                
                box.appendChild(grid);
                container.appendChild(box);
            }
        }

        function toggleAllUnivFields(select) {
            const cbs = document.querySelectorAll('input[name="univ-fields"]');
            cbs.forEach(cb => cb.checked = select);
        }

        async function startUniversalScrape() {
            const sourceKey = document.getElementById('univ-source-select').value;
            if (!sourceKey) {
                alert("Please select a data source first!");
                return;
            }

            const checkedCbs = document.querySelectorAll('input[name="univ-fields"]:checked');
            if (checkedCbs.length === 0) {
                alert("Please select at least one field to scrape!");
                return;
            }

            if (!isLocalConnected) {
                alert("Universal Scrapes must run in 'Local Engine Mode' with a server context running. Simulation mode does not support active extraction.");
                return;
            }

            const fieldKeys = Array.from(checkedCbs).map(cb => cb.value);
            const payload = {
                source: sourceKey,
                fields: fieldKeys,
                headless: document.getElementById('univ-headless-mode').checked,
                fast_mode: document.getElementById('univ-fast-mode').checked
            };

            const term = document.getElementById('univ-terminal-logs');
            term.innerHTML = `<div>> Initializing universal browser context...</div>`;

            try {
                const res = await fetch(`${getBaseUrl()}/api/scrape/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok) {
                    univActiveSessionId = data.session_id;
                    document.getElementById('univ-start-btn').disabled = true;
                    document.getElementById('univ-stop-btn').disabled = false;
                    
                    univActiveInterval = setInterval(pollUniversalStatus, 1000);
                } else {
                    term.innerHTML += `<div class="text-rose-400 font-semibold">> Failed to start: ${data.error}</div>`;
                }
            } catch(e) {
                term.innerHTML += `<div class="text-rose-400 font-semibold">> Connection error: ${e.message}</div>`;
            }
        }

        async function pollUniversalStatus() {
            if (!univActiveSessionId) return;
            try {
                const res = await fetch(`${getBaseUrl()}/api/scrape/status/${univActiveSessionId}`);
                const data = await res.json();
                if (res.ok) {
                    const term = document.getElementById('univ-terminal-logs');
                    term.innerHTML = '';
                    data.logs.forEach(l => {
                        const d = document.createElement('div');
                        d.textContent = l;
                        if (l.includes('Failed') || l.includes('Error')) d.className = 'text-rose-400';
                        else if (l.includes('successfully') || l.includes('Saved')) d.className = 'text-emerald-400';
                        term.appendChild(d);
                    });
                    term.scrollTop = term.scrollHeight;

                    // Update live table preview
                    const tbody = document.getElementById('univ-preview-tbody');
                    tbody.innerHTML = '';
                    if (data.logs.length > 0) {
                        data.logs.forEach((logLine, idx) => {
                            if (logLine.includes('→')) {
                                const parts = logLine.split('→');
                                const nameKey = parts[0].replace('>', '').trim();
                                const val = parts[1].trim();
                                const tr = document.createElement('tr');
                                tr.innerHTML = `
                                    <td class="py-2 px-4 font-mono text-[10px]">WEB_${idx}</td>
                                    <td class="py-2 px-4">Universal Target</td>
                                    <td class="py-2 px-4 font-mono text-zinc-400">${nameKey}</td>
                                    <td class="py-2 px-4 text-emerald-400 font-semibold">${val}</td>
                                `;
                                tbody.appendChild(tr);
                            }
                        });
                    }
                    if (tbody.innerHTML === '') {
                        tbody.innerHTML = `<tr><td colspan="4" class="py-4 text-center text-zinc-655 italic">Data stream active. Gathering fields...</td></tr>`;
                    }

                    if (data.finished) {
                        clearInterval(univActiveInterval);
                        univActiveSessionId = null;
                        document.getElementById('univ-start-btn').disabled = false;
                        document.getElementById('univ-stop-btn').disabled = true;
                        fetchUniversalHistory();
                    }
                }
            } catch(e) {
                console.error(e);
            }
        }

        async function stopUniversalScrape() {
            if (!univActiveSessionId) return;
            try {
                await fetch(`${getBaseUrl()}/api/scrape/stop/${univActiveSessionId}`, { method: 'POST' });
            } catch(e) {
                console.error(e);
            }
        }

        async function fetchUniversalHistory() {
            if (!isLocalConnected) {
                const tbody = document.getElementById('univ-history-tbody');
                tbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-zinc-655 italic">Connect to a local engine to view histories.</td></tr>';
                return;
            }
            try {
                const res = await fetch(`${getBaseUrl()}/api/history`);
                const data = await res.json();
                const tbody = document.getElementById('univ-history-tbody');
                tbody.innerHTML = '';
                
                if (data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-zinc-655 italic">No historical runs saved.</td></tr>';
                    return;
                }

                data.forEach(h => {
                    const tr = document.createElement('tr');
                    tr.className = 'border-b border-zinc-900 hover:bg-zinc-800/20';
                    tr.innerHTML = `
                        <td class="py-3 px-4">${h.timestamp}</td>
                        <td class="py-3 px-4 font-bold text-white">${h.platform}</td>
                        <td class="py-3 px-4 max-w-xs truncate">${h.fields}</td>
                        <td class="py-3 px-4 text-emerald-400">${h.status}</td>
                        <td class="py-3 px-4 text-center">${h.processed_properties}/${h.total_properties}</td>
                        <td class="py-3 px-4 text-center font-bold">${h.total_rows}</td>
                        <td class="py-3 px-4 text-right">
                            <a href="${getBaseUrl()}/api/download/${h.id}" class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-blue-600 transition text-[11px] font-bold">Download</a>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            } catch(e) {
                console.error(e);
            }
        }


        // ── TAB 4: ASYNC SCRAPER JS ─────────────────────────────────
        let activeAsyncTab = 'csv';
        let asyncActiveSessionId = null;
        let asyncActiveInterval = null;
        let parsedAsyncCSVRows = [];

        function switchAsyncSubTab(tabName) {
            activeAsyncTab = tabName;
            document.querySelectorAll('.async-sub-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');

            document.getElementById('async-sub-csv').style.display = tabName === 'csv' ? 'block' : 'none';
            document.getElementById('async-sub-manual').style.display = tabName === 'manual' ? 'block' : 'none';
        }

        function logAsyncTerminal(msg, isSuccess=false) {
            const term = document.getElementById('async-terminal-logs');
            const d = document.createElement('div');
            d.textContent = msg;
            if (isSuccess) d.className = 'text-emerald-400 font-bold';
            term.appendChild(d);
            term.scrollTop = term.scrollHeight;
        }

        function handleAsyncCSV(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(e) {
                const text = e.target.result;
                const rows = parseCSVText(text);
                parsedAsyncCSVRows = rows.map(r => r.url || r.link || r.hotel_name || r.name || '').filter(u => u.length > 0);
                
                document.getElementById('async-file-status').textContent = `✓ Selected: ${file.name}`;
                const preview = document.getElementById('async-csv-preview');
                preview.innerHTML = `Loaded ${parsedAsyncCSVRows.length} lines:\n` + parsedAsyncCSVRows.slice(0, 5).join('\n') + '\n...';
                logAsyncTerminal(`> Loaded CSV file: ${file.name} (${parsedAsyncCSVRows.length} targets)`);
            };
            reader.readAsText(file);
        }

        async function triggerAsyncScrape() {
            let urls = [];
            if (activeAsyncTab === 'manual') {
                const txt = document.getElementById('async-manual-urls').value.trim();
                if (txt) {
                    urls = txt.split('\n').map(u => u.trim()).filter(u => u.length > 0);
                }
            } else {
                urls = parsedAsyncCSVRows;
            }

            if (urls.length === 0) {
                alert("Please add manual URLs or upload a CSV file!");
                return;
            }

            if (!isLocalConnected) {
                // Simulation mode
                logAsyncTerminal(`> Spawning offline async simulator loop...`);
                document.getElementById('async-run-btn').disabled = true;
                document.getElementById('async-cancel-btn').disabled = false;
                
                let idx = 0;
                const simInterval = setInterval(() => {
                    if (idx >= urls.length) {
                        clearInterval(simInterval);
                        logAsyncTerminal("> Sim Completed. Result saved inside active exports session.", true);
                        document.getElementById('async-run-btn').disabled = false;
                        document.getElementById('async-cancel-btn').disabled = true;
                        document.getElementById('async-download-btn').disabled = false;
                        return;
                    }
                    const pct = Math.round(((idx+1)/urls.length)*100);
                    document.getElementById('async-live-progress-fill').style.width = `${pct}%`;
                    document.getElementById('async-live-status-text').textContent = `Scraping: ${urls[idx]}...`;
                    logAsyncTerminal(`> Extracted: ${urls[idx]} → status: success`, true);
                    idx++;
                }, 500);
                return;
            }

            const payload = {
                urls: urls,
                concurrency: parseInt(document.getElementById('async-concurrency-limit').value) || 10,
                sources: document.getElementById('async-sources-select').value,
                api_discovery: true
            };

            logAsyncTerminal(`> Spawning high-concurrency event loops for ${urls.length} targets...`);

            try {
                const res = await fetch(`${getBaseUrl()}/api/async_scraper/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok) {
                    asyncActiveSessionId = data.session_id;
                    document.getElementById('async-run-btn').disabled = true;
                    document.getElementById('async-cancel-btn').disabled = false;
                    document.getElementById('async-download-btn').disabled = true;
                    
                    asyncActiveInterval = setInterval(pollAsyncStatus, 1000);
                } else {
                    logAsyncTerminal(`> Error: ${data.error}`);
                }
            } catch(e) {
                logAsyncTerminal(`> Connection error: ${e.message}`);
            }
        }

        async function pollAsyncStatus() {
            if (!asyncActiveSessionId) return;
            try {
                const res = await fetch(`${getBaseUrl()}/api/async_scraper/status/${asyncActiveSessionId}`);
                const data = await res.json();
                if (res.ok) {
                    const val = data.progress_val || 0;
                    const max = data.progress_max || 1;
                    const pct = Math.round((val / max) * 100);
                    
                    document.getElementById('async-live-progress-fill').style.width = `${pct}%`;
                    document.getElementById('async-live-status-text').textContent = `${data.status_text || 'Running'} (${pct}%)`;

                    const term = document.getElementById('async-terminal-logs');
                    term.innerHTML = '';
                    data.logs.forEach(l => {
                        const d = document.createElement('div');
                        d.textContent = l;
                        if (l.includes('completed')) d.className = 'text-emerald-400 font-bold';
                        term.appendChild(d);
                    });
                    term.scrollTop = term.scrollHeight;

                    if (data.finished) {
                        logAsyncTerminal("> Concurrent scrape process finished!", true);
                        clearInterval(asyncActiveInterval);
                        document.getElementById('async-run-btn').disabled = false;
                        document.getElementById('async-cancel-btn').disabled = true;
                        document.getElementById('async-download-btn').disabled = false;
                    }
                }
            } catch(e) {
                console.error(e);
            }
        }

        async function stopAsyncScrape() {
            if (!asyncActiveSessionId) return;
            try {
                await fetch(`${getBaseUrl()}/api/async_scraper/stop/${asyncActiveSessionId}`, { method: 'POST' });
            } catch(e) {
                console.error(e);
            }
        }

        function downloadAsyncResults() {
            if (!isLocalConnected) {
                alert("Simulator output resolved. File can be viewed inside browser session.");
                return;
            }
            window.location.href = `${getBaseUrl()}/api/async_scraper/download/${asyncActiveSessionId}`;
        }


        // ── TAB 5: BULK OCM GENERATOR JS ────────────────────────────
        let ocmRecords = [];
        let ocmGenerationStop = false;

        function logOCMTerminal(msg, isSuccess=false) {
            const term = document.getElementById('ocm-terminal-logs');
            const d = document.createElement('div');
            d.textContent = msg;
            if (isSuccess) d.className = 'text-emerald-400 font-bold';
            term.appendChild(d);
            term.scrollTop = term.scrollHeight;
        }

        function downloadOCMSampleCSV() {
            const headers = "ownerName,hotelName,address,city,authDate,authHour,authMinute,ampm,ownerEmail,ownerPhone,emailSubject,recipientName,recipientEmail,format\n";
            const sample = "John Doe,FabHotel Grand Olive,12 Main St,New Delhi,2026-07-20,12,00,PM,john@gmail.com,9876543210,Letter of Authorization,Kiran Kumar,kiran.kumar@fabhotels.com,1\n";
            const csvContent = "data:text/csv;charset=utf-8," + encodeURIComponent(headers + sample);
            
            const link = document.createElement("a");
            link.setAttribute("href", csvContent);
            link.setAttribute("download", "ocm_sample.csv");
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            logOCMTerminal("> Downloaded bulk OCM CSV template sheet.");
        }

        function renderOCMTable() {
            const tbody = document.getElementById('ocm-tbody');
            tbody.innerHTML = '';
            
            if (ocmRecords.length === 0) {
                tbody.innerHTML = `
                    <tr id="ocm-empty-row">
                        <td colspan="14" class="py-6 text-center text-zinc-655 italic">No OCM records loaded. Add rows or upload a CSV to begin.</td>
                    </tr>
                `;
                return;
            }

            ocmRecords.forEach((r, idx) => {
                const tr = document.createElement('tr');
                tr.className = 'border-b border-zinc-900/60 hover:bg-zinc-800/10 transition';
                tr.innerHTML = `
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'ownerName', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.ownerName || ''}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'hotelName', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.hotelName || ''}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'address', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.address || ''}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'city', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.city || ''}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'authDate', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.authDate || ''}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'authHour', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.authHour || '12'}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'authMinute', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.authMinute || '00'}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'ampm', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.ampm || 'PM'}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'ownerEmail', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.ownerEmail || ''}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'ownerPhone', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.ownerPhone || ''}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'emailSubject', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.emailSubject || 'Letter of Authorization'}</td>
                    <td contenteditable="true" onblur="updateOCMCell(${idx}, 'format', this.textContent)" class="py-2.5 px-3 focus:bg-zinc-800/60 focus:outline-none">${r.format || '1'}</td>
                    <td id="ocm-row-status-${idx}" class="py-2.5 px-3 font-semibold text-zinc-400">Pending</td>
                    <td class="py-2.5 px-3 text-right whitespace-nowrap">
                        <button id="ocm-row-dl-${idx}" onclick="downloadSingleOCM(${idx})" disabled class="text-blue-400 hover:text-blue-300 font-bold px-2 py-0.5"><i class="fa-solid fa-download"></i></button>
                        <button onclick="deleteOCMRow(${idx})" class="text-rose-500 hover:text-rose-400 font-bold px-2 py-0.5"><i class="fa-solid fa-trash-can"></i></button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        function updateOCMCell(rowIdx, key, value) {
            if (ocmRecords[rowIdx]) {
                ocmRecords[rowIdx][key] = value.trim();
            }
        }

        function deleteOCMRow(idx) {
            ocmRecords.splice(idx, 1);
            renderOCMTable();
        }

        function addManualOCMRow() {
            const empty = {
                ownerName: 'AJAY BASUDEO YADAV',
                hotelName: 'Hotel Byland International',
                address: 'Mumbai',
                city: 'Mumbai',
                authDate: '2026-05-31',
                authHour: '12',
                authMinute: '00',
                ampm: 'AM',
                ownerEmail: 'owner@gmail.com',
                ownerPhone: '9987743404',
                emailSubject: 'Letter of Authorization',
                recipientName: 'Kiran Kumar',
                recipientEmail: 'kiran.kumar@fabhotels.com',
                format: '1'
            };
            ocmRecords.push(empty);
            renderOCMTable();
        }

        function clearAllOCMRows() {
            ocmRecords = [];
            renderOCMTable();
            logOCMTerminal("> Cleared all records.");
        }

        function handleOCMCSV(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            const reader = new FileReader();
            reader.onload = function(e) {
                const text = e.target.result;
                const rows = parseCSVText(text);
                ocmRecords = rows.map(r => {
                    return {
                        ownerName: r.ownerName || r.owner_name || '',
                        hotelName: r.hotelName || r.hotel_name || '',
                        address: r.address || '',
                        city: r.city || '',
                        authDate: r.authDate || r.date || '',
                        authHour: r.authHour || r.hour || '12',
                        authMinute: r.authMinute || r.minute || '00',
                        ampm: r.ampm || 'PM',
                        ownerEmail: r.ownerEmail || r.email || '',
                        ownerPhone: r.ownerPhone || r.phone || '',
                        emailSubject: r.emailSubject || 'Letter of Authorization',
                        recipientName: r.recipientName || 'Kiran Kumar',
                        recipientEmail: r.recipientEmail || 'kiran.kumar@fabhotels.com',
                        format: r.format || '1'
                    };
                });
                document.getElementById('ocm-csv-status').value = `Loaded: ${file.name} (${ocmRecords.length} rows)`;
                renderOCMTable();
                logOCMTerminal(`> Loaded CSV: ${file.name} (${ocmRecords.length} records).`);
            };
            reader.readAsText(file);
        }

        // PDF Generation Helper scripts matching C:/Users/CS05180/Desktop/ocm-generator/index.html logic
        function formatShortDateTime(date) {
            const d = String(date.getDate()).padStart(2,'0'),
                  mo = String(date.getMonth()+1).padStart(2,'0'),
                  h = date.getHours(),
                  m = date.getMinutes(),
                  ampm = h>=12?'PM':'AM';
            return d+'/'+mo+'/'+date.getFullYear()+', '+(h%12||12)+':'+String(m).padStart(2,'0')+' '+ampm;
        }

        function formatEmailDate(date) {
            const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
            const MONTHS_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
            const h = date.getHours(),
                  m = date.getMinutes(),
                  ampm = h>=12?'PM':'AM';
            return DAYS[date.getDay()]+', '+MONTHS_FULL[date.getMonth()]+' '+date.getDate()+', '+date.getFullYear()+' at '+(h%12||12)+':'+String(m).padStart(2,'0')+' '+ampm;
        }

        function formatRfcDate(date) {
            const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
            const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
            const h = String(date.getHours()).padStart(2,'0'),
                  m = String(date.getMinutes()).padStart(2,'0'),
                  s = String(date.getSeconds()).padStart(2,'0'),
                  offset = -date.getTimezoneOffset(),
                  sign = offset>=0?'+':'-',
                  offH = String(Math.floor(Math.abs(offset)/60)).padStart(2,'0'),
                  offM = String(Math.abs(offset)%60).padStart(2,'0');
            return DAYS[date.getDay()]+', '+date.getDate()+' '+MONTHS_SHORT[date.getMonth()]+' '+date.getFullYear()+' '+h+':'+m+':'+s+' '+sign+offH+offM;
        }

        function generateFormat1(doc, d) {
            const tpl = { brandColor: '#1a1a4e', logoText: 'fabHOTELS', senderName: 'Abhijeet Yadav', senderEmail: 'abhijeet.yadav@fabhotels.com', fontSize: '11', lineSpacing: '5.5', margin: '14' };
            const brandRgb = [26, 26, 78];
            const fs = parseInt(tpl.fontSize), ls = parseFloat(tpl.lineSpacing), mg = parseInt(tpl.margin);
            const bodyWidth = 200 - (mg*2);
            
            const now = new Date();
            const topDateStr = formatShortDateTime(now), fromDateStr = formatEmailDate(now);
            
            doc.setFontSize(9);
            doc.setFont('helvetica','bold');
            doc.text(topDateStr, mg, 12);
            doc.setFont('helvetica','normal');
            doc.text('FabHotels Mail - '+d.emailSubject+' Date: '+d.authDate, 200-mg, 12, {align:'right'});
            
            doc.setFontSize(22);
            doc.setFont('helvetica','bold');
            doc.setTextColor(...brandRgb);
            doc.text(tpl.logoText, mg, 28);
            
            doc.setTextColor(0,0,0);
            doc.setFontSize(9);
            doc.setFont('helvetica','normal');
            doc.text('<'+tpl.senderEmail+'>', 200-mg, 25, {align:'right'});
            doc.setFont('helvetica','bold');
            doc.text(tpl.senderName, 200-mg, 34, {align:'right'});
            
            doc.setDrawColor(200,200,200);
            doc.line(mg, 36, 200-mg, 36);
            
            doc.setFontSize(15);
            doc.text(d.emailSubject, mg, 46);
            doc.setFontSize(9);
            doc.setFont('helvetica','normal');
            doc.text('1 message', mg, 52);
            
            doc.setFont('helvetica','bold');
            doc.text(d.hotelName+'<'+d.ownerEmail+'>', mg, 60);
            doc.setFont('helvetica','normal');
            doc.text(fromDateStr, 200-mg, 60, {align:'right'});
            doc.text('To: "'+tpl.senderEmail+'" <'+tpl.senderEmail+'>', mg, 66);
            
            let y = 78;
            doc.setFontSize(fs);
            doc.text('To Whom It May Concern,', mg, y);
            y += ls*2;
            
            const b1 = 'I, '+d.ownerName+' owner of '+d.hotelName+', '+d.address+', hereby declare and authorize the appointment of Fabhotels (TRAVELSTACK TECH LIMITED) as the exclusive manager for the distribution of our inventory, rates, and hotel information on online sales channels in India, effective from the date of this letter.';
            const l1 = doc.splitTextToSize(b1, bodyWidth);
            doc.text(l1, mg, y);
            y += l1.length*ls + ls;
            
            const b2 = 'I confirm that I have terminated all contracts with any other Property Management Companies (PMCs) regarding the management of our online distribution.';
            const l2 = doc.splitTextToSize(b2, bodyWidth);
            doc.text(l2, mg, y);
            y += l2.length*ls + ls;
            
            const b3 = 'Furthermore, I consent and agree that Fabhotels has the right to migrate reviews and ratings from any previous listings on Online Travel Agencies (OTAs) to new listings created under their management.';
            const l3 = doc.splitTextToSize(b3, bodyWidth);
            doc.text(l3, mg, y);
            y += l3.length*ls + ls;
            
            const b4 = 'I hereby authorize Fabhotels to onboard '+d.hotelName+' located in '+d.city+' under their chain. This authorization is effective immediately and supersedes any prior agreements or arrangements.';
            const l4 = doc.splitTextToSize(b4, bodyWidth);
            doc.text(l4, mg, y);
            y += l4.length*ls + ls*2;
            
            if(y>255) { doc.addPage(); y = 20; }
            doc.text('Sincerely,', mg, y);
            y += ls*2;
            doc.setFont('helvetica','bold');
            doc.text(d.ownerName, mg, y);
            y += ls*1.5;
            doc.setFont('helvetica','normal');
            doc.text(d.ownerPhone, mg, y);
        }

        function generateFormat2(doc, d) {
            const tpl = { brandColor: '#1a1a4e', logoText: 'fabHOTELS', senderName: 'Abhijeet Yadav', senderEmail: 'abhijeet.yadav@fabhotels.com', fontSize: '11', lineSpacing: '5.5', margin: '14' };
            const fs = parseInt(tpl.fontSize), ls = parseFloat(tpl.lineSpacing), mg = parseInt(tpl.margin);
            const bodyWidth = 200 - (mg*2);
            
            const now = new Date();
            const fwdDateTime = formatRfcDate(now), topLeft = formatShortDateTime(now);
            
            doc.setFontSize(9);
            doc.setFont('helvetica','normal');
            doc.setTextColor(80,80,80);
            doc.text(topLeft, mg, 12);
            doc.setFont('helvetica','bold');
            doc.setTextColor(0,0,0);
            doc.text('Fwd: '+d.emailSubject, 105, 12, {align:'center'});
            
            doc.setFontSize(14);
            doc.text('Fwd: '+d.emailSubject, mg, 26);
            doc.setFontSize(9);
            doc.setFont('helvetica','bold');
            doc.text(tpl.senderName, 200-mg, 22, {align:'right'});
            doc.setFont('helvetica','normal');
            doc.setTextColor(80,80,80);
            doc.text('<'+tpl.senderEmail+'>', 200-mg, 28, {align:'right'});
            
            doc.setTextColor(0,0,0);
            doc.setDrawColor(200,200,200);
            doc.rect(mg+4, 36, bodyWidth-4, 50);
            
            let y = 44;
            doc.setFontSize(10);
            doc.setFont('helvetica','bold');
            doc.text(tpl.senderName+' <'+tpl.senderEmail+'>', mg+8, y);
            y += 6;
            doc.setFont('helvetica','normal');
            doc.text(fwdDateTime, mg+8, y);
            y += 8;
            doc.text('To "otateam" <otateam@fabhotels.com>', mg+12, y);
            y += 8;
            doc.text('Fyi', mg+8, y);
            y += 6;
            doc.text(tpl.senderName, mg+8, y);
            
            y = 94;
            doc.setDrawColor(180,180,180);
            doc.line(mg, y-3, 200-mg, y-3);
            
            doc.setFontSize(8);
            doc.setFont('helvetica','bold');
            doc.setTextColor(100,100,100);
            doc.text('=== Forwarded Message ===', mg, y);
            y += 7;
            doc.setFont('helvetica','normal');
            doc.setTextColor(0,0,0);
            doc.setFontSize(9);
            doc.text('From : '+d.ownerEmail, mg, y);
            y += 5;
            doc.text('To : abhijeet.yadav@fabhotels.com', mg, y);
            y += 5;
            doc.text('Date : '+fwdDateTime, mg, y);
            y += 5;
            doc.text('Subject : '+d.emailSubject, mg, y);
            y += 5;
            doc.line(mg, y+2, 200-mg, y+2);
            y += 8;
            
            doc.setFontSize(fs);
            doc.text("Subject: Authorization for Listing on OTA'S under FabHotels", mg, y);
            y += ls*1.5;
            doc.text('To Whom It May Concern,', mg, y);
            y += ls*1.8;
            
            const b1 = 'I, '+d.ownerName+', owner of '+d.hotelName+', located at '+d.address+', hereby confirm my association with FabHotels and list my property exclusively on OTA\'S under FabHotels\' management. FabHotels will handle the distribution of our inventory, rates, and hotel information on the OTA\'S platform.';
            const l1 = doc.splitTextToSize(b1, bodyWidth);
            doc.text(l1, mg, y);
            y += l1.length*ls + ls;
            
            const b2 = "I also request the removal of any parallel listings of my property on OTA'S, whether standalone or associated with other chains such as OYO or Treebo. Additionally, I request you to list my property under FabHotels on priority.";
            const l2 = doc.splitTextToSize(b2, bodyWidth);
            doc.text(l2, mg, y);
            y += l2.length*ls + ls;
            
            const b3 = "Furthermore, I consent to FabHotels migrating reviews and ratings from any previous listings on OTA'S to the new listing created under their management.";
            const l3 = doc.splitTextToSize(b3, bodyWidth);
            doc.text(l3, mg, y);
            y += l3.length*ls + ls;
            
            const b4 = 'This authorization is effective immediately and supersedes any prior agreements or arrangements.';
            const l4 = doc.splitTextToSize(b4, bodyWidth);
            doc.text(l4, mg, y);
            y += l4.length*ls + ls*1.5;
            
            if(y>255) { doc.addPage(); y = 20; }
            doc.setFont('helvetica','bold');
            doc.text(d.ownerName, mg, y);
            y += ls;
            doc.setFont('helvetica','normal');
            doc.text(d.ownerPhone, mg, y);
            y += ls;
            doc.text(d.hotelName, mg, y);
        }

        function generateFormat3(doc, d) {
            const tpl = { brandColor: '#1a1a4e', logoText: 'fabHOTELS', senderName: 'Abhijeet Yadav', senderEmail: 'abhijeet.yadav@fabhotels.com', fontSize: '11', lineSpacing: '5.5', margin: '14' };
            const fs = parseInt(tpl.fontSize), ls = parseFloat(tpl.lineSpacing), mg = parseInt(tpl.margin);
            const bodyWidth = 200 - (mg*2+4);
            
            const now = new Date();
            const nextDay = new Date(now);
            nextDay.setDate(nextDay.getDate()+1);
            
            const printDate = String(nextDay.getDate()).padStart(2,'0')+'/'+String(nextDay.getMonth()+1).padStart(2,'0')+'/'+nextDay.getFullYear();
            const emailDate = formatRfcDate(now);
            
            doc.setFontSize(10);
            doc.setFont('helvetica','bold');
            doc.text(printDate, mg+4, 15);
            doc.text('Zoho Mail - Print', 105, 15, {align:'center'});
            
            doc.setFontSize(9);
            let y = 28;
            const lx = mg+4, cx = lx+28, vx = lx+36;
            
            doc.setFont('helvetica','bold');
            doc.text('From', lx, y);
            doc.setFont('helvetica','normal');
            doc.text(':', cx, y);
            doc.text(d.hotelName+'<'+d.ownerEmail+'>', vx, y);
            y += 7;
            
            doc.setFont('helvetica','bold');
            doc.text('To', lx, y);
            doc.setFont('helvetica','normal');
            doc.text(':', cx, y);
            doc.text('"'+d.recipientName+'" <'+d.recipientEmail+'>', vx, y);
            y += 7;
            
            doc.setFont('helvetica','bold');
            doc.text('Subject', lx, y);
            doc.setFont('helvetica','normal');
            doc.text(':', cx, y);
            doc.text('Re: OTA NOC '+d.hotelName, vx, y);
            y += 7;
            
            doc.setFont('helvetica','bold');
            doc.text('Date', lx, y);
            doc.setFont('helvetica','normal');
            doc.text(':', cx, y);
            doc.text(emailDate, vx, y);
            
            y += 12;
            doc.setDrawColor(200,200,200);
            doc.line(mg+4, y, 200-mg-4, y);
            y += 15;
            
            doc.setFontSize(fs);
            doc.text('Date '+d.authDate, mg+4, y);
            y += ls*2;
            doc.text('To Whom It May Concern,', mg+4, y);
            y += ls*2;
            
            const b1 = 'I '+d.ownerName+' owner of '+d.hotelName+'\n'+d.address+', hereby declares and authorizes the appointment of Fabhotels (Casa Stays2 Pvt Ltd) as the exclusive manager for the distribution of our inventory, rates, and hotel information on online sales channels in India, effective from the date of this letter.';
            const l1 = doc.splitTextToSize(b1, bodyWidth);
            doc.text(l1, mg+4, y);
            y += l1.length*ls + ls*2;
            
            const b2 = 'I confirm that I have terminated all contracts with any other Property Management Companies (PMCs) regarding the management of our online distribution.';
            const l2 = doc.splitTextToSize(b2, bodyWidth);
            doc.text(l2, mg+4, y);
            y += l2.length*ls + ls*2;
            
            const b3 = 'Furthermore, I consent and agree that Fabhotels has the right to migrate reviews and ratings from any previous listings on Online Travel Agencies (OTAs) to new listings created under their management.';
            const l3 = doc.splitTextToSize(b3, bodyWidth);
            doc.text(l3, mg+4, y);
            y += l3.length*ls + ls*2;
            
            const b4 = 'I hereby authorize Fabhotels to onboard '+d.hotelName+' located in '+d.city+'. This authorization is effective immediately and supersedes any prior agreements or arrangements.';
            const l4 = doc.splitTextToSize(b4, bodyWidth);
            doc.text(l4, mg+4, y);
            y += l4.length*ls + ls*2;
            
            if(y>255) { doc.addPage(); y = 20; }
            doc.text('Sincerely,', mg+4, y);
            y += ls*2;
            doc.setFont('helvetica','bold');
            doc.text(d.ownerName, mg+4, y);
            y += ls*1.5;
            doc.setFont('helvetica','normal');
            doc.text(d.ownerPhone, mg+4, y);
        }

        async function triggerOCMGeneration() {
            if (ocmRecords.length === 0) {
                alert("Please add manual rows or upload an OCM CSV first!");
                return;
            }

            ocmGenerationStop = false;
            document.getElementById('ocm-run-btn').disabled = true;
            document.getElementById('ocm-stop-worker-btn').disabled = false;
            
            logOCMTerminal("🚀 Launching client-side OCM Generator...");
            
            const { jsPDF } = window.jspdf;
            const zip = new JSZip();
            
            let current = 0;
            const total = ocmRecords.length;
            const saveMode = document.getElementById('ocm-save-mode').value;

            for (let i = 0; i < total; i++) {
                if (ocmGenerationStop) {
                    logOCMTerminal("🛑 PDF generation cancelled by user.");
                    break;
                }

                current = i + 1;
                const pct = Math.round((current / total) * 100);
                document.getElementById('ocm-live-percent').textContent = `${pct}%`;
                
                const item = ocmRecords[i];
                const statusLbl = document.getElementById(`ocm-row-status-${i}`);
                if (statusLbl) {
                    statusLbl.textContent = "Generating...";
                    statusLbl.className = "py-2.5 px-3 font-semibold text-yellow-500 animate-pulse";
                }

                const doc = new jsPDF();
                const d = {
                    ownerName: item.ownerName || '',
                    hotelName: item.hotelName || '',
                    address: item.address || '',
                    city: item.city || '',
                    authDate: item.authDate || '',
                    ownerEmail: item.ownerEmail || '',
                    ownerPhone: item.ownerPhone || '',
                    emailSubject: item.emailSubject || 'Authorization for Listing on OTA\'S under FabHotels',
                    recipientName: item.recipientName || 'Kiran Kumar',
                    recipientEmail: item.recipientEmail || 'kiran.kumar@fabhotels.com'
                };

                const fmt = parseInt(item.format) || 1;
                if (fmt === 1) generateFormat1(doc, d);
                else if (fmt === 2) generateFormat2(doc, d);
                else generateFormat3(doc, d);

                // Save PDF to client memory
                const pdfBlob = doc.output('blob');
                const safeHotelName = (item.hotelName || 'hotel').replace(/[\\/*?:"<>|]/g, "");
                const filename = `FabHotel_${safeHotelName}_OCM_Format_${fmt}.pdf`;
                
                if (saveMode === 'individual') {
                    // Download directly
                    const link = document.createElement("a");
                    link.href = URL.createObjectURL(pdfBlob);
                    link.download = filename;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                } else {
                    // Add to zip folder
                    zip.file(filename, pdfBlob);
                }

                // Enable single row download button
                item.pdfDoc = doc;
                item.pdfName = filename;
                const singleDlBtn = document.getElementById(`ocm-row-dl-${i}`);
                if (singleDlBtn) singleDlBtn.disabled = false;

                if (statusLbl) {
                    statusLbl.textContent = "Completed";
                    statusLbl.className = "py-2.5 px-3 font-bold text-emerald-400";
                }

                logOCMTerminal(`✅ Generated PDF ${current}/${total}: ${filename}`, true);
                
                // Yield thread briefly
                await new Promise(resolve => setTimeout(resolve, 300));
            }

            if (!ocmGenerationStop) {
                if (saveMode === 'zip' && total > 0) {
                    logOCMTerminal("📦 Bundling all PDFs into ZIP archive...");
                    const content = await zip.generateAsync({ type: "blob" });
                    const link = document.createElement("a");
                    link.href = URL.createObjectURL(content);
                    link.download = "Generated_OCMs.zip";
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    logOCMTerminal("🎉 ZIP package downloaded successfully!", true);
                }
                logOCMTerminal("🎉 Bulk OCM Generation Completed successfully!", true);
            }

            document.getElementById('ocm-run-btn').disabled = false;
            document.getElementById('ocm-stop-worker-btn').disabled = true;
        }

        function downloadSingleOCM(idx) {
            const item = ocmRecords[idx];
            if (item && item.pdfDoc) {
                item.pdfDoc.save(item.pdfName || 'OCM.pdf');
            }
        }

        function stopOCMGeneration() {
            ocmGenerationStop = true;
        }

        // Shared utility to parse CSV text
        function parseCSVText(text) {
            const lines = text.split('\n');
            if (lines.length === 0) return [];
            const headers = lines[0].split(',').map(h => h.trim().replace(/^["']|["']$/g, ''));
            const list = [];
            for (let i = 1; i < lines.length; i++) {
                const line = lines[i].trim();
                if (!line) continue;
                const values = line.split(',').map(v => v.trim().replace(/^["']|["']$/g, ''));
                const obj = {};
                headers.forEach((h, idx) => {
                    obj[h] = values[idx] || '';
                });
                list.push(obj);
            }
            return list;
        }


        // ── ON LOAD INITIALIZATION ──────────────────────────────────
        window.addEventListener('DOMContentLoaded', () => {
            checkMMTSession();
            setInterval(checkMMTSession, 5000);
            loadUnivSources();
            fetchUniversalHistory();
        });
    