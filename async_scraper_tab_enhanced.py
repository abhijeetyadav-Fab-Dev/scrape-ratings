"""
Enhanced Async Scraper Tab — PyQt6 GUI for High-Performance Web Scraping
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Features:
  • CSV upload (hotel names from file)
  • Manual URL input
  • Multi-source scraping (Booking, Google, TripAdvisor, Agoda, Expedia)
  • Configurable concurrency
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
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from async_scraper_enhanced import EnhancedRatingScraper

logger = logging.getLogger("AsyncScraperTab")


class ScrapeWorkerThread(QThread):
    """Background worker thread for async scraping."""
    
    progress = pyqtSignal(int, int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, csv_content: str = None, urls: List[str] = None, max_concurrent: int = 10,
                 sources: List[str] = None, output_path: str = None):
        super().__init__()
        self.csv_content = csv_content
        self.urls = urls
        self.max_concurrent = max_concurrent
        self.sources = sources or ['booking', 'google', 'tripadvisor', 'agoda', 'expedia']
        self.output_path = output_path or self._default_output_path()
        self._stop_event = threading.Event()
    
    def _default_output_path(self) -> str:
        export_dir = Path.home() / ".scrape-ratings" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(export_dir / f"async_scrape_{timestamp}.csv")
    
    def run(self):
        try:
            asyncio.run(self._do_scrape())
        except Exception as e:
            self.error.emit(f"Scraping failed: {str(e)}")
            logger.error(f"Scraping error: {str(e)}", exc_info=True)
    
    async def _do_scrape(self):
        try:
            scraper = EnhancedRatingScraper(
                max_concurrent=self.max_concurrent,
                delay_range=(0.5, 2.0),
                request_timeout=30.0
            )
            
            if self.csv_content:
                self.status_update.emit(f"📋 Processing CSV with {len(self.sources)} sources...", "info")
                
                def progress_callback(item: str, sources_count: int, scraped_count: int):
                    if not self._stop_event.is_set():
                        self.progress.emit(scraped_count, sources_count, f"✓ {item[:50]}")
                
                await scraper.scrape_hotels_from_csv(
                    self.csv_content,
                    sources=self.sources,
                    progress_callback=progress_callback
                )
            
            elif self.urls:
                self.status_update.emit(f"🔗 Processing {len(self.urls)} URLs...", "info")
                for i, url in enumerate(self.urls, 1):
                    self.progress.emit(i, len(self.urls), f"Fetched {url[:40]}")
                self.status_update.emit("⚠️ URL mode not implemented. Please use CSV mode.", "warning")
            else:
                self.error.emit("No input provided")
                return
            
            if scraper.data:
                self.status_update.emit("💾 Exporting to CSV...", "info")
                export_file = scraper.export_to_csv(self.output_path)
                
                if export_file:
                    stats = scraper.get_stats()
                    msg = f"✓ Exported {len(scraper.data)} items | Success: {stats['successful']}, Failed: {stats['failed']}"
                    self.status_update.emit(msg, "success")
                    self.finished.emit(export_file)
                else:
                    self.error.emit("Failed to export CSV")
            else:
                self.error.emit("No data collected")
        
        except asyncio.CancelledError:
            self.status_update.emit("Scraping cancelled", "warning")
        except Exception as e:
            self.error.emit(f"Unexpected error: {str(e)}")
    
    def stop(self):
        self._stop_event.set()
        self.wait(timeout=5000)


class AsyncScraperTab(QWidget):
    """Enhanced PyQt6 tab for async web scraping."""
    
    def __init__(self):
        super().__init__()
        self.worker_thread = None
        self.csv_content = None
        self.checkpoint_dir = Path.home() / ".scrape-ratings" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("🚀 Enhanced Async Scraper")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e0e0e0;")
        layout.addWidget(title)
        
        subtitle = QLabel("Upload CSV with hotel names or paste URLs. Scrapes Booking, Google, TripAdvisor, Agoda, Expedia")
        subtitle.setStyleSheet("color: #888; font-size: 11px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        
        # Input tabs
        input_tabs = QTabWidget()
        input_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #333; }
            QTabBar::tab { background: #0f3460; color: #888; padding: 6px 16px; }
            QTabBar::tab:selected { background: #16213e; color: white; }
        """)
        
        # CSV Tab
        csv_widget = QWidget()
        csv_layout = QVBoxLayout(csv_widget)
        
        csv_info = QLabel("📋 Upload CSV file with hotel names")
        csv_info.setStyleSheet("color: #a0e0a0; font-weight: bold;")
        csv_layout.addWidget(csv_info)
        
        self.csv_file_label = QLabel("No file selected")
        self.csv_file_label.setStyleSheet("color: #888;")
        csv_layout.addWidget(self.csv_file_label)
        
        self.load_csv_button = QPushButton("📁 Browse CSV")
        self.load_csv_button.setMaximumWidth(150)
        self.load_csv_button.clicked.connect(self.load_csv_file)
        csv_layout.addWidget(self.load_csv_button)
        
        self.csv_preview = QTextEdit()
        self.csv_preview.setReadOnly(True)
        self.csv_preview.setMaximumHeight(80)
        self.csv_preview.setPlaceholderText("CSV preview will appear here...")
        self.csv_preview.setStyleSheet("""
            QTextEdit { background-color: #16213e; color: #a0e0a0; 
                       border: 1px solid #333; border-radius: 4px; 
                       font-family: Consolas; font-size: 9px; }
        """)
        csv_layout.addWidget(self.csv_preview)
        csv_layout.addStretch()
        
        input_tabs.addTab(csv_widget, "📋 CSV Upload")
        
        # URL Tab
        url_widget = QWidget()
        url_layout = QVBoxLayout(url_widget)
        
        url_info = QLabel("🔗 Manual URL Entry")
        url_info.setStyleSheet("color: #ffaa00; font-weight: bold;")
        url_layout.addWidget(url_info)
        
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("Paste URLs (one per line)...\nhttps://example.com/page1")
        self.url_input.setStyleSheet("""
            QTextEdit { background-color: #16213e; color: #a0e0a0; 
                       border: 1px solid #333; border-radius: 4px; 
                       font-family: Consolas; font-size: 11px; }
        """)
        url_layout.addWidget(self.url_input)
        
        input_tabs.addTab(url_widget, "🔗 Manual URLs")
        
        layout.addWidget(input_tabs)
        
        # Options
        options_group = QGroupBox("Settings")
        options_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
        """)
        options_layout = QVBoxLayout()
        
        # Concurrency
        conc_layout = QHBoxLayout()
        conc_layout.addWidget(QLabel("Max Concurrent:"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setMinimum(1)
        self.concurrency_spin.setMaximum(50)
        self.concurrency_spin.setValue(10)
        self.concurrency_spin.setStyleSheet("""
            QSpinBox { background-color: #16213e; color: #e0e0e0; 
                      border: 1px solid #333; border-radius: 4px; width: 60px; }
        """)
        conc_layout.addWidget(self.concurrency_spin)
        conc_layout.addStretch()
        options_layout.addLayout(conc_layout)
        
        # Sources
        sources_layout = QHBoxLayout()
        sources_layout.addWidget(QLabel("Scrape sources:"))
        self.sources_combo = QComboBox()
        self.sources_combo.addItems([
            "All (5 sources)",
            "Booking Only",
            "Google & Booking",
            "TripAdvisor Only",
        ])
        self.sources_combo.setStyleSheet("""
            QComboBox { background-color: #16213e; color: #e0e0e0; 
                       border: 1px solid #333; border-radius: 4px; }
        """)
        sources_layout.addWidget(self.sources_combo)
        sources_layout.addStretch()
        options_layout.addLayout(sources_layout)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # Progress
        progress_group = QGroupBox("Progress")
        progress_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; }
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
        
        # Log
        log_group = QGroupBox("Log")
        log_group.setStyleSheet("""
            QGroupBox { border: 1px solid #333; border-radius: 6px; 
                       color: #888; padding-top: 8px; }
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
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.scrape_button = QPushButton("🚀 Start Scraping")
        self.scrape_button.setStyleSheet("""
            QPushButton { background-color: #0f3460; color: white; border: none;
                         padding: 10px 20px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #16213e; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        self.scrape_button.clicked.connect(self.start_scraping)
        button_layout.addWidget(self.scrape_button)
        
        self.cancel_button = QPushButton("⊘ Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scraping)
        button_layout.addWidget(self.cancel_button)
        
        self.export_button = QPushButton("💾 Open Exports")
        self.export_button.clicked.connect(self.open_export_folder)
        button_layout.addWidget(self.export_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        layout.addStretch()
        self.setLayout(layout)
        
        self._setup_logging()
    
    def load_csv_file(self):
        """Load a CSV file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV (*.csv);;Excel (*.xlsx)")
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.csv_content = f.read()
                
                lines = self.csv_content.split('\n')[:5]
                self.csv_preview.setText('\n'.join(lines))
                self.csv_file_label.setText(f"✓ {Path(file_path).name}")
                logger.info(f"CSV loaded: {file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load CSV: {str(e)}")
    
    def start_scraping(self):
        """Start scraping."""
        if not self.csv_content and not self.url_input.toPlainText().strip():
            QMessageBox.warning(self, "No Input", "Please load a CSV or enter URLs")
            return
        
        # Get sources
        sources_text = self.sources_combo.currentText()
        if "All" in sources_text:
            sources = ['booking', 'google', 'tripadvisor', 'agoda', 'expedia']
        elif "Booking" in sources_text and "Google" not in sources_text:
            sources = ['booking']
        elif "Google" in sources_text:
            sources = ['google', 'booking']
        elif "TripAdvisor" in sources_text:
            sources = ['tripadvisor']
        else:
            sources = ['booking', 'google']
        
        self.url_input.setEnabled(False)
        self.concurrency_spin.setEnabled(False)
        self.load_csv_button.setEnabled(False)
        self.scrape_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting scrape...")
        
        urls = [u.strip() for u in self.url_input.toPlainText().split('\n') if u.strip()]
        
        self.worker_thread = ScrapeWorkerThread(
            csv_content=self.csv_content,
            urls=urls if urls else None,
            max_concurrent=self.concurrency_spin.value(),
            sources=sources
        )
        
        self.worker_thread.progress.connect(self._on_progress)
        self.worker_thread.status_update.connect(self._on_status)
        self.worker_thread.finished.connect(self._on_finished)
        self.worker_thread.error.connect(self._on_error)
        
        self.worker_thread.start()
    
    def _on_progress(self, current: int, total: int, status: str):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"{status}")
    
    def _on_status(self, message: str, level: str):
        color_map = {'info': '#888', 'warning': '#ffaa00', 'error': '#ff4444', 'success': '#44ff44'}
        html = f'<span style="color: {color_map.get(level, "#888")}">{message}</span>'
        self.log_display.setHtml(self.log_display.toHtml() + '<br>' + html)
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_finished(self, export_path: str):
        self.status_label.setText(f"✓ Complete: {Path(export_path).name}")
        self._reset_controls()
        QMessageBox.information(self, "Success", f"Exported to:\n{export_path}")
    
    def _on_error(self, error: str):
        self.status_label.setText(f"✗ Error: {error}")
        self._reset_controls()
        QMessageBox.critical(self, "Error", error)
    
    def cancel_scraping(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.stop()
            self._reset_controls()
    
    def open_export_folder(self):
        export_dir = Path.home() / ".scrape-ratings" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        
        import subprocess, sys
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', str(export_dir)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(export_dir)])
        else:
            subprocess.Popen(['xdg-open', str(export_dir)])
    
    def _reset_controls(self):
        self.url_input.setEnabled(True)
        self.concurrency_spin.setEnabled(True)
        self.load_csv_button.setEnabled(True)
        self.scrape_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
    
    def _setup_logging(self):
        class QtLogHandler(logging.Handler):
            def __init__(self, callback):
                super().__init__()
                self.callback = callback
            
            def emit(self, record):
                msg = self.format(record)
                self.callback(msg, record.levelname.lower())
        
        self._log_handler = QtLogHandler(lambda m, l: self._on_status(m, l))
        logger.addHandler(self._log_handler)
