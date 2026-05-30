import os
import csv
import base64
import re
import threading
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QProgressBar, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QGroupBox, QGridLayout, QFrame, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from playwright.sync_api import sync_playwright

class OCMGeneratorWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)  # current, total
    row_status_signal = pyqtSignal(int, str, str)  # row_idx, status, file_path
    finished_signal = pyqtSignal(dict)

    def __init__(self, items, output_dir):
        super().__init__()
        self.items = items
        self.output_dir = Path(output_dir)
        self.is_running = True

    def run(self):
        self.log_signal.emit("🚀 Starting Bulk OCM Generation Worker...")
        os.makedirs(self.output_dir, exist_ok=True)
        
        index_html_path = Path("C:/Users/CS05180/Desktop/ocm-generator/index.html")
        if not index_html_path.exists():
            self.log_signal.emit("❌ Error: Could not find ocm-generator index.html at C:/Users/CS05180/Desktop/ocm-generator/index.html")
            self.finished_signal.emit({"error": "Index HTML not found"})
            return
            
        url = index_html_path.as_uri()
        self.log_signal.emit(f"📄 Loaded local template: {url}")
        
        total = len(self.items)
        success_count = 0
        
        try:
            with sync_playwright() as p:
                self.log_signal.emit("🌐 Launching headless browser context...")
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.goto(url)
                
                for idx, item in enumerate(self.items):
                    if not self.is_running:
                        self.log_signal.emit("🛑 Generation paused/stopped by user.")
                        break
                        
                    self.progress_signal.emit(idx + 1, total)
                    self.row_status_signal.emit(idx, "Generating", "")
                    
                    owner_name = item.get("ownerName", "").strip()
                    hotel_name = item.get("hotelName", "").strip()
                    address = item.get("address", "").strip()
                    city = item.get("city", "").strip()
                    auth_date = item.get("authDate", "").strip()
                    auth_hour = item.get("authHour", "12").strip()
                    auth_minute = item.get("authMinute", "00").strip()
                    ampm = item.get("ampm", "AM").strip().upper()
                    owner_email = item.get("ownerEmail", "").strip()
                    owner_phone = item.get("ownerPhone", "").strip()
                    email_subject = item.get("emailSubject", "Letter of Authorization").strip()
                    recipient_name = item.get("recipientName", "Kiran Kumar").strip()
                    recipient_email = item.get("recipientEmail", "kiran.kumar@fabhotels.com").strip()
                    fmt = str(item.get("format", "1")).strip()
                    
                    if not owner_name or not hotel_name or not address or not city:
                        self.log_signal.emit(f"⚠️ [Row {idx+1}] Skipping: Missing required fields (Owner, Hotel, Address, or City).")
                        self.row_status_signal.emit(idx, "Failed", "")
                        continue
                        
                    self.log_signal.emit(f"✍️ [Row {idx+1}/{total}] Preparing PDF for '{hotel_name}'...")
                    
                    # Fill inputs using Javascript
                    try:
                        # Clear state and set form values
                        page.evaluate(f"""(data) => {{
                            document.getElementById('ownerName').value = data.ownerName;
                            document.getElementById('hotelName').value = data.hotelName;
                            document.getElementById('address').value = data.address;
                            document.getElementById('city').value = data.city;
                            document.getElementById('authDate').value = data.authDate;
                            document.getElementById('authHour').value = data.authHour;
                            document.getElementById('authMinute').value = data.authMinute;
                            
                            // Handle AM/PM toggle
                            document.querySelectorAll('.ampm-btn').forEach(btn => {{
                                const isActive = btn.dataset.ampm === data.ampm;
                                btn.classList.toggle('active', isActive);
                                btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
                            }});
                            
                            document.getElementById('ownerEmail').value = data.ownerEmail;
                            document.getElementById('ownerPhone').value = data.ownerPhone;
                            document.getElementById('emailSubject').value = data.emailSubject;
                            
                            // Format index
                            const fmtIdx = parseInt(data.format) - 1;
                            document.querySelectorAll('.format-option').forEach((o, i) => {{
                                o.classList.toggle('active', i === fmtIdx);
                            }});
                            
                            // Update selectedFormat globally
                            window.selectedFormat = parseInt(data.format);
                            
                            document.querySelectorAll('.field-format3').forEach(el => {{
                                el.style.display = window.selectedFormat === 3 ? 'block' : 'none';
                            }});
                            
                            if (window.selectedFormat === 3) {{
                                document.getElementById('recipientName').value = data.recipientName;
                                document.getElementById('recipientEmail').value = data.recipientEmail;
                            }}
                            
                            // Submit form
                            const form = document.getElementById('ocmForm');
                            form.dispatchEvent(new Event('submit', {{ cancelable: true, bubbles: true }}));
                        }}""", {
                            "ownerName": owner_name,
                            "hotelName": hotel_name,
                            "address": address,
                            "city": city,
                            "authDate": auth_date,
                            "authHour": auth_hour,
                            "authMinute": auth_minute,
                            "ampm": ampm,
                            "ownerEmail": owner_email,
                            "ownerPhone": owner_phone,
                            "emailSubject": email_subject,
                            "recipientName": recipient_name,
                            "recipientEmail": recipient_email,
                            "format": fmt
                        })
                        
                        # Wait for page evaluation and rendering
                        page.wait_for_timeout(500)
                        
                        # Extract PDF Base64
                        pdf_datauri = page.evaluate("window.generatedDoc.output('datauristring')")
                        if not pdf_datauri or "," not in pdf_datauri:
                            raise Exception("Failed to retrieve generatedDoc output from browser context.")
                            
                        base64_pdf = pdf_datauri.split(",")[1]
                        pdf_bytes = base64.b64decode(base64_pdf)
                        
                        # Clean filename
                        safe_hotel_name = re.sub(r'[\\/*?:"<>|]', "", hotel_name)
                        filename = f"FabHotel_{safe_hotel_name}_OCM_Format_{fmt}.pdf"
                        dest_path = self.output_dir / filename
                        
                        with open(dest_path, "wb") as f:
                            f.write(pdf_bytes)
                            
                        self.log_signal.emit(f"✅ Saved PDF to: {dest_path}")
                        self.row_status_signal.emit(idx, "Completed", str(dest_path))
                        success_count += 1
                        
                    except Exception as e:
                        self.log_signal.emit(f"❌ [Row {idx+1}] PDF generation failed: {e}")
                        self.row_status_signal.emit(idx, "Failed", "")
                        
                browser.close()
                
        except Exception as e:
            self.log_signal.emit(f"❌ Playwright execution error: {e}")
            self.finished_signal.emit({"error": str(e)})
            return
            
        self.log_signal.emit(f"\n🎉 Bulk OCM Generation Completed! Generated {success_count} of {total} PDFs.")
        self.finished_signal.emit({"success_count": success_count, "total": total})

class BulkOCMGeneratorTab(QWidget):
    def __init__(self):
        super().__init__()
        self.items = []
        self.worker = None
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # Title
        title = QLabel("Bulk OCM Generator (Owner Confirmation Mail)")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Subtitle / Description
        desc = QLabel("Automate Owner Confirmation Mail / Letter of Authorization PDFs generation in bulk using loaded CSV files.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #aaa; font-size: 12px; margin-bottom: 5px;")
        layout.addWidget(desc)
        
        # Form / Control Group
        controls_group = QGroupBox("Configuration")
        controls_layout = QGridLayout(controls_group)
        
        # CSV Browse row
        controls_layout.addWidget(QLabel("CSV Input:"), 0, 0)
        self.csv_path_input = QLineEdit()
        self.csv_path_input.setPlaceholderText("Browse CSV file containing OCM records...")
        self.csv_path_input.setStyleSheet("background: #16213e; color: white; border: 1px solid #444; border-radius: 4px; padding: 6px;")
        controls_layout.addWidget(self.csv_path_input, 0, 1)
        
        self.browse_btn = QPushButton("Browse CSV")
        self.browse_btn.clicked.connect(self.browse_csv)
        self.browse_btn.setStyleSheet("padding: 6px 12px;")
        controls_layout.addWidget(self.browse_btn, 0, 2)
        
        # Output Folder row
        controls_layout.addWidget(QLabel("Output Folder:"), 1, 0)
        self.output_dir_input = QLineEdit()
        default_output = str(Path.home() / "Downloads" / "Generated_OCMs")
        self.output_dir_input.setText(default_output)
        self.output_dir_input.setStyleSheet("background: #16213e; color: white; border: 1px solid #444; border-radius: 4px; padding: 6px;")
        controls_layout.addWidget(self.output_dir_input, 1, 1)
        
        self.dest_btn = QPushButton("Browse Dest")
        self.dest_btn.clicked.connect(self.browse_destination)
        self.dest_btn.setStyleSheet("padding: 6px 12px;")
        controls_layout.addWidget(self.dest_btn, 1, 2)
        
        layout.addWidget(controls_group)
        
        # Action Buttons row
        action_layout = QHBoxLayout()
        self.sample_btn = QPushButton("Download Sample CSV")
        self.sample_btn.clicked.connect(self.download_sample)
        self.sample_btn.setStyleSheet("background-color: #3498db; font-weight: bold; padding: 8px 16px;")
        action_layout.addWidget(self.sample_btn)
        
        self.add_row_btn = QPushButton("Add Manual Row")
        self.add_row_btn.clicked.connect(self.add_manual_row)
        self.add_row_btn.setStyleSheet("background-color: #27ae60; font-weight: bold; padding: 8px 16px;")
        action_layout.addWidget(self.add_row_btn)
        
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self.clear_table)
        action_layout.addWidget(self.clear_btn)
        
        action_layout.addStretch()
        
        self.start_btn = QPushButton("Generate PDFs")
        self.start_btn.clicked.connect(self.start_generation)
        self.start_btn.setStyleSheet("background-color: #e94560; font-weight: bold; padding: 8px 24px;")
        action_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_generation)
        self.stop_btn.setEnabled(False)
        action_layout.addWidget(self.stop_btn)
        
        layout.addLayout(action_layout)
        
        # Table of records
        self.table = QTableWidget()
        self.headers = [
            "Owner Name", "Hotel Name", "Address", "City", 
            "Auth Date", "Hour", "Minute", "AM/PM", 
            "Owner Email", "Owner Phone", "Subject", "Format", "Status", "Open PDF"
        ]
        self.table.setColumnCount(len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #1a1a2e; gridline-color: #333; color: white; }
            QHeaderView::section { background-color: #0f3460; color: white; padding: 5px; border: 1px solid #333; }
            QTableWidget::item { padding: 4px; }
        """)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        
        # Progress and logging
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("QProgressBar { text-align: center; color: white; } QProgressBar::chunk { background-color: #e94560; }")
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        self.log.setStyleSheet("background-color: #16213e; color: #a0e0a0; font-family: Consolas; font-size: 11px;")
        layout.addWidget(self.log)
        
    def browse_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select OCM CSV Input", "", "CSV Files (*.csv)"
        )
        if file_path:
            self.csv_path_input.setText(file_path)
            self.load_csv(file_path)
            
    def browse_destination(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self.output_dir_input.text()
        )
        if dir_path:
            self.output_dir_input.setText(dir_path)
            
    def load_csv(self, file_path):
        self.table.setRowCount(0)
        self.items = []
        self.log.append(f"📁 Loading OCM records from: {file_path}")
        
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                
                # Check headers
                fields = reader.fieldnames if reader.fieldnames else []
                self.log.append(f"Headers found: {', '.join(fields)}")
                
                # Normalization mapping
                header_map = {}
                for fld in fields:
                    lfld = fld.lower().strip().replace(" ", "").replace("_", "")
                    if lfld in ("ownername", "owner"): header_map[fld] = "ownerName"
                    elif lfld in ("hotelname", "hotel"): header_map[fld] = "hotelName"
                    elif lfld in ("address", "fulladdress"): header_map[fld] = "address"
                    elif lfld in ("city", "onboardingcity"): header_map[fld] = "city"
                    elif lfld in ("authdate", "date"): header_map[fld] = "authDate"
                    elif lfld in ("authhour", "hour"): header_map[fld] = "authHour"
                    elif lfld in ("authminute", "minute"): header_map[fld] = "authMinute"
                    elif lfld in ("ampm", "timeampm"): header_map[fld] = "ampm"
                    elif lfld in ("owneremail", "email"): header_map[fld] = "ownerEmail"
                    elif lfld in ("ownerphone", "phone", "mobile"): header_map[fld] = "ownerPhone"
                    elif lfld in ("emailsubject", "subject"): header_map[fld] = "emailSubject"
                    elif lfld in ("recipientname", "to"): header_map[fld] = "recipientName"
                    elif lfld in ("recipientemail", "toemail"): header_map[fld] = "recipientEmail"
                    elif lfld in ("format", "pdfformat", "ocmformat"): header_map[fld] = "format"

                row_idx = 0
                for row in reader:
                    item = {
                        "ownerName": "", "hotelName": "", "address": "", "city": "",
                        "authDate": "2026-05-31", "authHour": "12", "authMinute": "00", "ampm": "AM",
                        "ownerEmail": "", "ownerPhone": "", "emailSubject": "Letter of Authorization",
                        "recipientName": "Kiran Kumar", "recipientEmail": "kiran.kumar@fabhotels.com",
                        "format": "1"
                    }
                    
                    for orig, norm in header_map.items():
                        if row.get(orig):
                            item[norm] = row[orig]
                            
                    self.items.append(item)
                    self.add_table_row(row_idx, item)
                    row_idx += 1
                    
            self.log.append(f"✅ Loaded {len(self.items)} records into the grid.")
            
        except Exception as e:
            self.log.append(f"❌ Error loading CSV: {e}")
            
    def add_table_row(self, row_idx, item):
        self.table.insertRow(row_idx)
        
        # Populate columns
        cols = [
            item.get("ownerName", ""), item.get("hotelName", ""),
            item.get("address", ""), item.get("city", ""),
            item.get("authDate", ""), item.get("authHour", ""),
            item.get("authMinute", ""), item.get("ampm", ""),
            item.get("ownerEmail", ""), item.get("ownerPhone", ""),
            item.get("emailSubject", ""), item.get("format", ""),
            "Pending", "Open"
        ]
        
        for col_idx, text in enumerate(cols):
            cell = QTableWidgetItem(str(text))
            if col_idx == 12:  # Status column is read-only
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            elif col_idx == 13:  # Open PDF action column
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                cell.setForeground(QColor("#3498db"))
            self.table.setItem(row_idx, col_idx, cell)
            
    def add_manual_row(self):
        row_idx = self.table.rowCount()
        default_item = {
            "ownerName": "AJAY BASUDEO YADAV", "hotelName": "Hotel Byland International",
            "address": "Mumbai", "city": "Mumbai",
            "authDate": "2026-05-31", "authHour": "12", "authMinute": "00", "ampm": "AM",
            "ownerEmail": "owner@gmail.com", "ownerPhone": "9987743404",
            "emailSubject": "Letter of Authorization", "format": "1"
        }
        self.items.append(default_item)
        self.add_table_row(row_idx, default_item)
        self.table.scrollToBottom()
        self.log.append("➕ Added manual template row. Double-click any cell to edit.")

    def clear_table(self):
        self.table.setRowCount(0)
        self.items = []
        self.progress_bar.setValue(0)
        self.log.append("🗑️ Table cleared.")

    def download_sample(self):
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save Sample OCM CSV", str(Path.home() / "Downloads" / "ocm_sample.csv"), "CSV Files (*.csv)"
        )
        if dest:
            try:
                headers = [
                    "Owner Name", "Hotel Name", "Address", "City", 
                    "Auth Date", "Hour", "Minute", "AM/PM", 
                    "Owner Email", "Owner Phone", "Subject", "Format",
                    "Recipient Name", "Recipient Email"
                ]
                with open(dest, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    writer.writerow([
                        "AJAY BASUDEO YADAV", "Hotel Byland International",
                        "Street Road, Area, Mumbai, Maharashtra, 400001", "Mumbai",
                        "2026-05-31", "01", "02", "PM", "owner@gmail.com", "9987743404",
                        "Letter of Authorization", "1", "Kiran Kumar", "kiran.kumar@fabhotels.com"
                    ])
                self.log.append(f"✅ Sample CSV saved to: {dest}")
            except Exception as e:
                self.log.append(f"❌ Failed to save sample: {e}")

    def sync_items_from_table(self):
        """Update items dictionary from current table cells (user edits)"""
        self.items = []
        for row in range(self.table.rowCount()):
            item = {
                "ownerName": self.table.item(row, 0).text(),
                "hotelName": self.table.item(row, 1).text(),
                "address": self.table.item(row, 2).text(),
                "city": self.table.item(row, 3).text(),
                "authDate": self.table.item(row, 4).text(),
                "authHour": self.table.item(row, 5).text(),
                "authMinute": self.table.item(row, 6).text(),
                "ampm": self.table.item(row, 7).text(),
                "ownerEmail": self.table.item(row, 8).text(),
                "ownerPhone": self.table.item(row, 9).text(),
                "emailSubject": self.table.item(row, 10).text(),
                "format": self.table.item(row, 11).text(),
                "recipientName": "Kiran Kumar",
                "recipientEmail": "kiran.kumar@fabhotels.com"
            }
            self.items.append(item)

    def start_generation(self):
        self.sync_items_from_table()
        if not self.items:
            self.log.append("❌ Error: No items to generate PDFs for. Load a CSV or add manual rows.")
            return
            
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.browse_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.sample_btn.setEnabled(False)
        self.add_row_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        
        output_dir = self.output_dir_input.text().strip()
        self.worker = OCMGeneratorWorker(self.items, output_dir)
        self.worker.log_signal.connect(self.log.append)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.row_status_signal.connect(self.update_row_status)
        self.worker.finished_signal.connect(self.on_worker_finished)
        self.worker.start()
        
    def stop_generation(self):
        if self.worker:
            self.worker.is_running = False
            self.log.append("⏳ Stopping OCM Generator worker thread...")
            
    def update_progress(self, current, total):
        pct = int((current / total) * 100)
        self.progress_bar.setValue(pct)
        
    def update_row_status(self, row_idx, status, file_path):
        # Update Status cell
        cell_status = self.table.item(row_idx, 12)
        cell_status.setText(status)
        if status == "Completed":
            cell_status.setBackground(QColor("#2a5c2a"))
        elif status == "Failed":
            cell_status.setBackground(QColor("#5c2a2a"))
        elif status == "Generating":
            cell_status.setBackground(QColor("#5c5c2a"))
            
        # Bind file click action
        if file_path:
            cell_action = self.table.item(row_idx, 13)
            cell_action.setText("Open PDF")
            
    def on_worker_finished(self, results):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.browse_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.sample_btn.setEnabled(True)
        self.add_row_btn.setEnabled(True)
        self.worker = None
        
        # Connect Double Click to open PDF
        try:
            self.table.cellDoubleClicked.disconnect()
        except:
            pass
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        
    def on_cell_double_clicked(self, row, col):
        if col == 13:  # Open PDF Column
            status_item = self.table.item(row, 12)
            if status_item and status_item.text() == "Completed":
                # Find file path dynamically
                hotel_name = self.table.item(row, 1).text()
                fmt = self.table.item(row, 11).text()
                safe_hotel_name = re.sub(r'[\\/*?:"<>|]', "", hotel_name)
                filename = f"FabHotel_{safe_hotel_name}_OCM_Format_{fmt}.pdf"
                full_path = Path(self.output_dir_input.text().strip()) / filename
                if full_path.exists():
                    import os
                    os.startfile(str(full_path))
                    self.log.append(f"📂 Opened file: {full_path}")
                else:
                    self.log.append(f"❌ Error: File not found at {full_path}")
