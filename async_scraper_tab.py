"""
Async Scraper Tab — PyQt6 GUI for High-Performance Web Scraping
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Features:
  • CSV upload (hotel names, search terms)
  • Manual URL input
  • Multi-source scraping (Booking, Google, TripAdvisor, Agoda, Expedia)
  • Configurable concurrency
  • Optional API endpoint discovery
  • Real-time progress tracking
  • CSV export with results
"""

import asyncio
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any
import csv
from io import StringIO

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame, QCheckBox, QGroupBox, QProgressBar,
    QSpinBox, QFileDialog, QMessageBox, QComboBox, QTabWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect
from PyQt6.QtGui import QFont, QColor

from async_scraper_enhanced import EnhancedRatingScraper

logger = logging.getLogger("AsyncScraperTab")


# ────────────────────────────────────────────────────────────
#  Worker Thread for Async Operations
# ────────────────────────────────────────────────────────────

class ScrapeWorkerThread(QThread):
    """Background worker thread for async scraping."""
    
    # Signals
    progress = pyqtSignal(int, int, str)  # (current, total, url)
    status_update = pyqtSignal(str, str)  # (message, level: 'info'/'warning'/'error'/'success')
    finished = pyqtSignal(str)  # (export_path)
    error = pyqtSignal(str)  # (error_message)
    
    def __init__(self, urls: List[str], max_concurrent: int = 10, 
                 discover_apis: bool = False, output_path: str = None):
        super().__init__()
        self.urls = urls
        self.max_concurrent = max_concurrent
        self.discover_apis_flag = discover_apis
        self.output_path = output_path or self._default_output_path()
        self._stop_event = threading.Event()
    
    def _default_output_path(self) -> str:
        """Generate default output path."""
        export_dir = Path.home() / ".scrape-ratings" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(export_dir / f"scrape_{timestamp}.csv")
    
    def run(self):
        """Execute scraping in background thread."""
        try:
            # Run async operations in this thread
            asyncio.run(self._do_scrape())
        except Exception as e:
            self.error.emit(f"Scraping failed: {str(e)}")
            logger.error(f"Scraping error: {str(e)}", exc_info=True)
    
    async def _do_scrape(self):
        """Main async scraping workflow."""
        try:
            scraper = RatingScraper(
                max_concurrent=self.max_concurrent,
                delay_range=(0.5, 2.0),
                request_timeout=30.0
            )
            
            # Step 1: API discovery (optional)
            if self.discover_apis_flag and self.urls:
                self.status_update.emit("🔍 Discovering API endpoints...", "info")
                try:
                    base_url = self.urls[0]
                    apis = await scraper.discover_apis(base_url)
                    msg = f"Found {len(apis)} API endpoints"
                    self.status_update.emit(msg, "success")
                    logger.info(msg)
                except Exception as e:
                    self.status_update.emit(f"API discovery skipped: {str(e)}", "warning")
                    logger.warning(f"API discovery error: {str(e)}")
            
            # Step 2: Scrape URLs
            self.status_update.emit(f"🚀 Starting to scrape {len(self.urls)} URLs...", "info")
            
            def progress_callback(current: int, total: int, url: str, result: Optional[Dict]):
                if not self._stop_event.is_set():
                    status = "✓" if result else "✗"
                    self.progress.emit(current, total, f"{status} {url[:60]}")
            
            await scraper.scrape_urls(self.urls, progress_callback=progress_callback)
            
            # Step 3: Export to CSV
            if scraper.data:
                self.status_update.emit("💾 Exporting to CSV...", "info")
                export_file = scraper.export_to_csv(self.output_path)
                
                if export_file:
                    stats = scraper.get_stats()
                    msg = f"✓ Exported {len(scraper.data)} items to {export_file} ({stats['successful']} successful, {stats['failed']} failed)"
                    self.status_update.emit(msg, "success")
                    logger.info(msg)
                    self.finished.emit(export_file)
                else:
                    self.error.emit("Failed to export CSV")
            else:
                msg = "No data collected from scraping"
                self.status_update.emit(msg, "warning")
                self.error.emit(msg)
        
        except asyncio.CancelledError:
            self.status_update.emit("Scraping cancelled", "warning")
            logger.info("Scraping cancelled by user")
        except Exception as e:
            self.error.emit(f"Unexpected error: {str(e)}")
            logger.error(f"Unexpected error during scraping: {str(e)}", exc_info=True)
    
    def stop(self):
        """Request scraping to stop."""
        self._stop_event.set()
        self.wait(timeout=5000)


# ────────────────────────────────────────────────────────────
#  Main PyQt6 Tab Widget
# ────────────────────────────────────────────────────────────

class AsyncScraperTab(QWidget):
    """PyQt6 tab for async web scraping."""
    
    def __init__(self):
        super().__init__()
        self.worker_thread = None
        self.checkpoint_dir = Path.home() / ".scrape-ratings" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        self._init_ui()
        self._load_checkpoint()
    
    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # ── Title ────────────────────────────────────────────
        title = QLabel("🚀 Enhanced Async Scraper")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e0e0e0;")
        layout.addWidget(title)
        
        subtitle = QLabel("Upload CSV with hotel names OR enter URLs to scrape multiple sources (Booking, Google, TripAdvisor, Agoda, Expedia)")
        subtitle.setStyleSheet("color: #888; font-size: 11px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        
        # ── Input Mode Tabs ──────────────────────────────────
        input_tabs = QTabWidget()
        input_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #333; }
            QTabBar::tab { background: #0f3460; color: #888; padding: 6px 16px; }
            QTabBar::tab:selected { background: #16213e; color: white; }
        """)
        
        # Tab 1: CSV Upload
        csv_widget = QWidget()
        csv_layout = QVBoxLayout(csv_widget)
        
        csv_info = QLabel("📋 Upload CSV with hotel names")
        csv_info.setStyleSheet("color: #a0e0a0; font-weight: bold;")
        csv_layout.addWidget(csv_info)
        
        self.csv_file_label = QLabel("No file selected")
        self.csv_file_label.setStyleSheet("color: #888;")
        csv_layout.addWidget(self.csv_file_label)
        
        csv_btn_layout = QHBoxLayout()
        self.load_csv_button = QPushButton("📁 Browse CSV")
        self.load_csv_button.setMaximumWidth(200)
        self.load_csv_button.clicked.connect(self.load_csv_file)
        csv_btn_layout.addWidget(self.load_csv_button)
        csv_btn_layout.addStretch()
        csv_layout.addLayout(csv_btn_layout)
        
        self.csv_preview = QTextEdit()
        self.csv_preview.setReadOnly(True)
        self.csv_preview.setMaximumHeight(100)
        self.csv_preview.setPlaceholderText("CSV preview will appear here...")
        self.csv_preview.setStyleSheet("""
            QTextEdit { background-color: #16213e; color: #a0e0a0; 
                       border: 1px solid #333; border-radius: 4px; 
                       font-family: Consolas; font-size: 10px; }
        """)
        csv_layout.addWidget(self.csv_preview)
        
        input_tabs.addTab(csv_widget, "📋 CSV Upload")
        
        # Tab 2: Manual URLs
        url_widget = QWidget()
        url_layout = QVBoxLayout(url_widget)
        
        url_info = QLabel("🔗 Manual URL Entry")
        url_info.setStyleSheet("color: #ffaa00; font-weight: bold;")
        url_layout.addWidget(url_info)
        
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("Paste URLs here (one per line)...\nhttps://example.com/page1\nhttps://example.com/page2")
        self.url_input.setMinimumHeight(100)
        self.url_input.setStyleSheet("""
            QTextEdit { background-color: #16213e; color: #a0e0a0; 
                       border: 1px solid #333; border-radius: 4px; 
                       font-family: Consolas; font-size: 11px; }
        """)
        url_layout.addWidget(self.url_input)
        
        input_tabs.addTab(url_widget, "🔗 Manual URLs")
        
        layout.addWidget(input_tabs)
        
        # ── Options Group ────────────────────────────────────
        options_group = QGroupBox("Settings")
        options_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
        """)
        options_layout = QVBoxLayout()
        
        # Concurrency control
        concurrency_layout = QHBoxLayout()
        concurrency_layout.addWidget(QLabel("Max Concurrent Requests:"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setMinimum(1)
        self.concurrency_spin.setMaximum(50)
        self.concurrency_spin.setValue(10)
        self.concurrency_spin.setStyleSheet("""
            QSpinBox { background-color: #16213e; color: #e0e0e0; 
                      border: 1px solid #333; border-radius: 4px; }
        """)
        concurrency_layout.addWidget(self.concurrency_spin)
        concurrency_layout.addStretch()
        options_layout.addLayout(concurrency_layout)
        
        # Sources selection
        sources_layout = QHBoxLayout()
        sources_layout.addWidget(QLabel("Sources to scrape:"))
        self.sources_combo = QComboBox()
        self.sources_combo.addItems([
            "All (Booking, Google, TripAdvisor, Agoda, Expedia)",
            "Booking Only",
            "Google Only",
            "TripAdvisor Only",
        ])
        self.sources_combo.setStyleSheet("""
            QComboBox { background-color: #16213e; color: #e0e0e0; 
                       border: 1px solid #333; border-radius: 4px; }
        """)
        sources_layout.addWidget(self.sources_combo)
        sources_layout.addStretch()
        options_layout.addLayout(sources_layout)
        
        # API Discovery checkbox
        self.api_discovery_check = QCheckBox("Auto-detect API Endpoints (optional)")
        self.api_discovery_check.setStyleSheet("color: #e0e0e0; margin-top: 8px;")
        options_layout.addWidget(self.api_discovery_check)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # ── Progress Section ─────────────────────────────────
        progress_group = QGroupBox("Progress")
        progress_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
        """)
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #333; border-radius: 4px; text-align: center;
                          color: white; background-color: #0a0a0a; }
            QProgressBar::chunk { background-color: #e94560; border-radius: 3px; }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #a0e0a0;")
        progress_layout.addWidget(self.status_label)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        # ── Log Display ──────────────────────────────────────
        log_group = QGroupBox("Log")
        log_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
        """)
        log_layout = QVBoxLayout()
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(100)
        self.log_display.setStyleSheet("""
            QTextEdit { background-color: #0a0a0a; color: #888; 
                       border: 1px solid #333; border-radius: 4px; 
                       font-family: Consolas; font-size: 10px; }
        """)
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # ── Action Buttons ───────────────────────────────────
        button_layout = QHBoxLayout()
        
        self.scrape_button = QPushButton("🚀 Start Scraping")
        self.scrape_button.setStyleSheet("""
            QPushButton { background-color: #0f3460; color: white; border: none;
                         padding: 10px 20px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #16213e; }
            QPushButton:pressed { background-color: #0a1f3a; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        self.scrape_button.clicked.connect(self.start_scraping)
        button_layout.addWidget(self.scrape_button)
        
        self.cancel_button = QPushButton("⊘ Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setStyleSheet("""
            QPushButton { background-color: #555; color: white; border: none;
                         padding: 10px 20px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #666; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        self.cancel_button.clicked.connect(self.cancel_scraping)
        button_layout.addWidget(self.cancel_button)
        
        self.export_button = QPushButton("💾 Open Export Folder")
        self.export_button.setStyleSheet("""
            QPushButton { background-color: #0f3460; color: white; border: none;
                         padding: 10px 20px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #16213e; }
        """)
        self.export_button.clicked.connect(self.open_export_folder)
        button_layout.addWidget(self.export_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Setup logging handler
        self._setup_logging()
    
    def load_csv_file(self):
        """Load a CSV file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select CSV File", "", "CSV Files (*.csv);;Excel Files (*.xlsx)")
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.csv_content = f.read()
                
                # Show preview
                lines = self.csv_content.split('\n')[:5]
                preview = '\n'.join(lines)
                self.csv_preview.setText(preview)
                self.csv_file_label.setText(f"✓ Loaded: {Path(file_path).name}")
                logger.info(f"CSV loaded: {file_path}")
                
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load CSV: {str(e)}")
                logger.error(f"CSV load error: {str(e)}")
        
        # ── Options Group ────────────────────────────────────
        options_group = QGroupBox("Settings")
        options_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
        """)
        options_layout = QVBoxLayout()
        
        # Concurrency control
        concurrency_layout = QHBoxLayout()
        concurrency_layout.addWidget(QLabel("Max Concurrent Requests:"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setMinimum(1)
        self.concurrency_spin.setMaximum(50)
        self.concurrency_spin.setValue(10)
        self.concurrency_spin.setStyleSheet("""
            QSpinBox { background-color: #16213e; color: #e0e0e0; 
                      border: 1px solid #333; border-radius: 4px; }
        """)
        concurrency_layout.addWidget(self.concurrency_spin)
        concurrency_layout.addStretch()
        options_layout.addLayout(concurrency_layout)
        
        # API Discovery checkbox
        self.api_discovery_check = QCheckBox("Auto-detect API Endpoints (optional)")
        self.api_discovery_check.setStyleSheet("color: #e0e0e0; margin-top: 8px;")
        options_layout.addWidget(self.api_discovery_check)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # ── Progress Section ─────────────────────────────────
        progress_group = QGroupBox("Progress")
        progress_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
        """)
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #333; border-radius: 4px; text-align: center;
                          color: white; background-color: #0a0a0a; }
            QProgressBar::chunk { background-color: #e94560; border-radius: 3px; }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #a0e0a0;")
        progress_layout.addWidget(self.status_label)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        # ── Log Display ──────────────────────────────────────
        log_group = QGroupBox("Log")
        log_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
        """)
        log_layout = QVBoxLayout()
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(120)
        self.log_display.setStyleSheet("""
            QTextEdit { background-color: #0a0a0a; color: #888; 
                       border: 1px solid #333; border-radius: 4px; 
                       font-family: Consolas; font-size: 10px; }
        """)
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # ── Action Buttons ───────────────────────────────────
        button_layout = QHBoxLayout()
        
        self.scrape_button = QPushButton("🚀 Start Scraping")
        self.scrape_button.setStyleSheet("""
            QPushButton { background-color: #0f3460; color: white; border: none;
                         padding: 10px 20px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #16213e; }
            QPushButton:pressed { background-color: #0a1f3a; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        self.scrape_button.clicked.connect(self.start_scraping)
        button_layout.addWidget(self.scrape_button)
        
        self.cancel_button = QPushButton("⊘ Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setStyleSheet("""
            QPushButton { background-color: #555; color: white; border: none;
                         padding: 10px 20px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #666; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        self.cancel_button.clicked.connect(self.cancel_scraping)
        button_layout.addWidget(self.cancel_button)
        
        self.export_button = QPushButton("💾 Open Export Folder")
        self.export_button.setStyleSheet("""
            QPushButton { background-color: #0f3460; color: white; border: none;
                         padding: 10px 20px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #16213e; }
        """)
        self.export_button.clicked.connect(self.open_export_folder)
        button_layout.addWidget(self.export_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Setup logging handler
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging to display in UI."""
        # Create custom handler that emits signals
        class QtLogHandler(logging.Handler):
            def __init__(self, log_signal):
                super().__init__()
                self.log_signal = log_signal
            
            def emit(self, record):
                msg = self.format(record)
                level = record.levelname
                self.log_signal.emit(msg, level.lower())
        
        # Store as instance variable and connect
        self._log_handler = QtLogHandler(lambda msg, level: self._append_log(msg, level))
        logger.addHandler(self._log_handler)
    
    def _append_log(self, message: str, level: str):
        """Append message to log display with color coding."""
        color_map = {
            'info': '#888',
            'warning': '#ffaa00',
            'error': '#ff4444',
            'success': '#44ff44',
        }
        color = color_map.get(level, '#888')
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        html = f'<span style="color: {color};">[{timestamp}] {message}</span>'
        
        current = self.log_display.toHtml()
        self.log_display.setHtml(current + '<br>' + html)
        
        # Auto-scroll to bottom
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def start_scraping(self):
        """Start scraping with current settings."""
        urls = [url.strip() for url in self.url_input.toPlainText().split('\n') if url.strip()]
        
        if not urls:
            QMessageBox.warning(self, "No URLs", "Please enter at least one URL to scrape")
            return
        
        # Disable controls
        self.url_input.setEnabled(False)
        self.concurrency_spin.setEnabled(False)
        self.api_discovery_check.setEnabled(False)
        self.scrape_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        
        # Reset progress
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(urls))
        self.status_label.setText(f"Scraping {len(urls)} URLs...")
        
        logger.info(f"Starting scrape of {len(urls)} URLs")
        
        # Create and start worker thread
        self.worker_thread = ScrapeWorkerThread(
            urls=urls,
            max_concurrent=self.concurrency_spin.value(),
            discover_apis=self.api_discovery_check.isChecked()
        )
        
        # Connect signals
        self.worker_thread.progress.connect(self._on_progress)
        self.worker_thread.status_update.connect(self._on_status_update)
        self.worker_thread.finished.connect(self._on_finished)
        self.worker_thread.error.connect(self._on_error)
        
        self.worker_thread.start()
        
        # Save checkpoint
        self._save_checkpoint(urls)
    
    def _on_progress(self, current: int, total: int, url: str):
        """Update progress bar."""
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Progress: {current}/{total} - {url}")
    
    def _on_status_update(self, message: str, level: str):
        """Handle status updates from worker."""
        self._append_log(message, level)
    
    def _on_finished(self, export_path: str):
        """Scraping finished successfully."""
        self.status_label.setText(f"✓ Scraping complete. Exported to {Path(export_path).name}")
        self._reset_controls()
        QMessageBox.information(self, "Success", f"Scraping complete!\n\nExported to:\n{export_path}")
    
    def _on_error(self, error_message: str):
        """Handle scraping error."""
        self.status_label.setText(f"✗ Error: {error_message}")
        self._reset_controls()
        QMessageBox.critical(self, "Error", error_message)
    
    def cancel_scraping(self):
        """Cancel ongoing scraping."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.stop()
            self._reset_controls()
            self.status_label.setText("Scraping cancelled")
    
    def open_export_folder(self):
        """Open export directory in file explorer."""
        export_dir = Path.home() / ".scrape-ratings" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        
        import subprocess
        import sys
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', str(export_dir)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(export_dir)])
        else:
            subprocess.Popen(['xdg-open', str(export_dir)])
    
    def _reset_controls(self):
        """Re-enable controls after scraping."""
        self.url_input.setEnabled(True)
        self.concurrency_spin.setEnabled(True)
        self.api_discovery_check.setEnabled(True)
        self.scrape_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
    
    def _save_checkpoint(self, urls: List[str]):
        """Save progress checkpoint."""
        checkpoint = {
            'timestamp': datetime.now().isoformat(),
            'urls': urls,
            'concurrency': self.concurrency_spin.value(),
            'api_discovery': self.api_discovery_check.isChecked(),
        }
        checkpoint_file = self.checkpoint_dir / f"async_scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            checkpoint_file.write_text(json.dumps(checkpoint, indent=2))
            logger.info(f"Checkpoint saved: {checkpoint_file.name}")
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {str(e)}")
    
    def _load_checkpoint(self):
        """Load last checkpoint if available."""
        try:
            checkpoint_files = sorted(self.checkpoint_dir.glob("async_scraper_*.json"), reverse=True)
            if checkpoint_files:
                latest = checkpoint_files[0]
                checkpoint = json.loads(latest.read_text())
                
                # Restore URLs
                self.url_input.setPlainText('\n'.join(checkpoint.get('urls', [])))
                self.concurrency_spin.setValue(checkpoint.get('concurrency', 10))
                self.api_discovery_check.setChecked(checkpoint.get('api_discovery', False))
                
                logger.info(f"Loaded checkpoint: {latest.name}")
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {str(e)}")
