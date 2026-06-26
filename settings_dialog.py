import os
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QLineEdit, QSpinBox, QCheckBox, QGroupBox, QFormLayout, QMessageBox,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt
import db_cache

SETTINGS_PATH = Path(__file__).parent / "settings.json"

def get_default_settings():
    return {
        "enable_proxies": False,
        "proxy_list": "",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "jitter_min": 1,
        "jitter_max": 3,
        "enable_jitter": False
    }

def load_settings():
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
                # merge with defaults to avoid missing keys
                defaults = get_default_settings()
                defaults.update(data)
                return defaults
        except Exception:
            pass
    return get_default_settings()

def save_settings(settings):
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=4)
    except Exception:
        pass

class SettingsDialog(QDialog):
    def __init__(self, parent=None, on_resume_callback=None):
        super().__init__(parent)
        self.setWindowTitle("Stealth & Cache Settings")
        self.setMinimumSize(600, 500)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a2e; }
            QLabel { color: #e0e0e0; }
            QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 10px; color: #e94560; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox, QTableWidget {
                background-color: #16213e; color: white; border: 1px solid #333; border-radius: 4px; padding: 4px;
            }
            QPushButton { background-color: #0f3460; color: white; border: none; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background-color: #16213e; }
        """)
        self.on_resume_callback = on_resume_callback
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Load Current Settings
        self.current_settings = load_settings()

        # Group 1: Stealth Panel
        stealth_group = QGroupBox("Stealth & Browser Settings")
        stealth_layout = QFormLayout(stealth_group)

        self.cb_proxies = QCheckBox("Enable Proxy Rotation")
        self.cb_proxies.setChecked(self.current_settings.get("enable_proxies", False))
        stealth_layout.addRow(self.cb_proxies)

        self.proxy_input = QTextEdit()
        self.proxy_input.setPlaceholderText("Enter proxies (one per line, e.g. http://ip:port or http://user:pass@ip:port)")
        self.proxy_input.setText(self.current_settings.get("proxy_list", ""))
        self.proxy_input.setMaximumHeight(80)
        stealth_layout.addRow("Proxy List:", self.proxy_input)

        self.ua_input = QLineEdit()
        self.ua_input.setText(self.current_settings.get("user_agent", ""))
        stealth_layout.addRow("User Agent:", self.ua_input)

        # Jitter Delay Row
        jitter_row = QHBoxLayout()
        self.cb_jitter = QCheckBox("Enable Random Delays")
        self.cb_jitter.setChecked(self.current_settings.get("enable_jitter", False))
        jitter_row.addWidget(self.cb_jitter)

        self.spin_min = QSpinBox()
        self.spin_min.setRange(0, 60)
        self.spin_min.setValue(self.current_settings.get("jitter_min", 1))
        jitter_row.addWidget(QLabel("Min (s):"))
        jitter_row.addWidget(self.spin_min)

        self.spin_max = QSpinBox()
        self.spin_max.setRange(0, 120)
        self.spin_max.setValue(self.current_settings.get("jitter_max", 3))
        jitter_row.addWidget(QLabel("Max (s):"))
        jitter_row.addWidget(self.spin_max)

        stealth_layout.addRow("Jitter (Delay):", jitter_row)
        layout.addWidget(stealth_group)

        # Group 2: Cache Settings
        cache_group = QGroupBox("SQLite Cache & Stats")
        cache_layout = QVBoxLayout(cache_group)
        
        self.stats_lbl = QLabel("Loading stats...")
        cache_layout.addWidget(self.stats_lbl)

        btn_row = QHBoxLayout()
        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        self.clear_cache_btn.setStyleSheet("background-color: #c0392b;")
        btn_row.addWidget(self.clear_cache_btn)

        self.refresh_stats_btn = QPushButton("Refresh Stats")
        self.refresh_stats_btn.clicked.connect(self.update_stats)
        btn_row.addWidget(self.refresh_stats_btn)
        cache_layout.addLayout(btn_row)

        layout.addWidget(cache_group)

        # Group 3: Resumable Active Batch Runs
        batch_group = QGroupBox("Resumable Runs")
        batch_layout = QVBoxLayout(batch_group)

        self.batch_table = QTableWidget(0, 5)
        self.batch_table.setHorizontalHeaderLabels(["Run ID", "Input File", "Progress", "Status", "Timestamp"])
        self.batch_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.batch_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.batch_table.setMaximumHeight(120)
        batch_layout.addWidget(self.batch_table)

        self.resume_btn = QPushButton("Resume Selected Run")
        self.resume_btn.clicked.connect(self.resume_selected)
        self.resume_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        batch_layout.addWidget(self.resume_btn)

        layout.addWidget(batch_group)

        # Dialog Buttons
        dialog_btns = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setStyleSheet("background-color: #2e7d32; font-weight: bold;")
        self.save_btn.clicked.connect(self.save_and_close)
        dialog_btns.addWidget(self.save_btn)

        self.close_btn = QPushButton("Cancel")
        self.close_btn.clicked.connect(self.reject)
        dialog_btns.addWidget(self.close_btn)
        layout.addLayout(dialog_btns)

        # Initial Loads
        self.update_stats()
        self.load_batch_runs()

    def update_stats(self):
        stats = db_cache.get_cache_stats()
        self.stats_lbl.setText(
            f"Cached Ratings: {stats['ratings_cached']} items\n"
            f"Cached Parallel Finder Matches: {stats['finder_cached']} items"
        )

    def clear_cache(self):
        reply = QMessageBox.question(self, "Clear Cache", "Are you sure you want to clear all SQLite caches?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            db_cache.clear_all_caches()
            self.update_stats()
            self.load_batch_runs()
            QMessageBox.information(self, "Caches Cleared", "All cached queries and run states have been removed.")

    def load_batch_runs(self):
        self.batch_table.setRowCount(0)
        runs = db_cache.get_all_batch_runs()
        for r in runs:
            row = self.batch_table.rowCount()
            self.batch_table.insertRow(row)
            self.batch_table.setItem(row, 0, QTableWidgetItem(r.get("run_id", "")))
            self.batch_table.setItem(row, 1, QTableWidgetItem(os.path.basename(r.get("input_file", ""))))
            self.batch_table.setItem(row, 2, QTableWidgetItem(f"{r.get('current_index', 0)}/{r.get('total_items', 0)}"))
            self.batch_table.setItem(row, 3, QTableWidgetItem(r.get("status", "")))
            
            import datetime
            ts = r.get("timestamp", 0)
            date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else ""
            self.batch_table.setItem(row, 4, QTableWidgetItem(date_str))

    def resume_selected(self):
        selected = self.batch_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a batch run from the table to resume.")
            return

        run_id = selected[0].text()
        run_data = db_cache.get_batch_run(run_id)
        if run_data:
            if run_data.get("status") == "FINISHED":
                QMessageBox.information(self, "Already Finished", "This run has already finished successfully.")
                return
            
            if self.on_resume_callback:
                self.on_resume_callback(run_data)
                self.accept()
            else:
                QMessageBox.information(self, "Resume Run", f"Resuming run {run_id} from index {run_data['current_index']}.")

    def save_and_close(self):
        self.current_settings["enable_proxies"] = self.cb_proxies.isChecked()
        self.current_settings["proxy_list"] = self.proxy_input.toPlainText().strip()
        self.current_settings["user_agent"] = self.ua_input.text().strip()
        self.current_settings["enable_jitter"] = self.cb_jitter.isChecked()
        self.current_settings["jitter_min"] = self.spin_min.value()
        self.current_settings["jitter_max"] = self.spin_max.value()

        save_settings(self.current_settings)
        self.accept()
