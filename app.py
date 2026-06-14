"""
Hotel Data Tools — Ratings Scraper, God Mode, & Universal Scraper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Thin container that organises three independent scraper modules:
  - Ratings Scraper  (ratings_tab.py)  → hotel ratings by platform
  - God Mode         (god_mode.py)     → scan any page, build links
  - Universal Scraper (universal_scraper.py) → extranet data extraction
"""

import sys, os, argparse
import ctypes
from pathlib import Path

# AppUserModelID block removed to restore default icon grouping

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget,
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent


# ========================================================================
# Import the three tab widgets
# ========================================================================
from ratings_tab import RatingsTab
from god_mode import GodModeTab
from universal_scraper import UniversalScraperTab
from ocm_tab import BulkOCMGeneratorTab


class MainWindow(QMainWindow):
    """Thin container with three top-level tabs."""

    def __init__(self, csv_path=None, workers=10):
        super().__init__()
        self.setWindowTitle("Hotel Data Tools v2.1 — Ratings, God Mode & Universal Scraper")

        icon_path = str(Path(__file__).parent / "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setMinimumSize(950, 800)
        self.setStyleSheet("""
            QMainWindow { background-color: #1a1a2e; }
            QLabel { color: #e0e0e0; }
            QPushButton { background-color: #0f3460; color: white; border: none;
                         padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background-color: #16213e; }
            QPushButton:disabled { background-color: #333; color: #666; }
            QProgressBar { border: 1px solid #333; border-radius: 4px; text-align: center;
                          color: white; }
            QProgressBar::chunk { background-color: #e94560; border-radius: 3px; }
            QTextEdit { background-color: #16213e; color: #a0e0a0; border: 1px solid #333;
                       border-radius: 4px; font-family: Consolas; font-size: 11px; }
        """)
        self.setAcceptDrops(True)

        # ── Tabbed interface ─────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #1a1a2e; }
            QTabBar::tab { background: #0f3460; color: #888; padding: 8px 20px;
                          margin-right: 2px; border-top-left-radius: 6px;
                          border-top-right-radius: 6px; font-size: 12px; }
            QTabBar::tab:selected { background: #16213e; color: white; }
            QTabBar::tab:hover { background: #1a3a6a; }
        """)
        self.setCentralWidget(self.tabs)

        # Tab 1 — Ratings Scraper (platform sub-tabs)
        self.tabs.addTab(RatingsTab(csv_path=csv_path, workers=workers), "Ratings Scraper")

        # Tab 2 — God Mode (Page Scanner + Link Builder)
        self.tabs.addTab(GodModeTab(), "God Mode")

        # Tab 3 — Universal Scraper (extranet data extraction)
        self.tabs.addTab(UniversalScraperTab(), "Universal Scraper")

        # Tab 4 — Bulk OCM Generator
        self.tabs.addTab(BulkOCMGeneratorTab(), "Bulk OCM Generator")

        # ── Floating AI Agent Overlay Corner Integration ───────────
        from agent_overlay import FloatingAgentWidget
        self.agent = FloatingAgentWidget(self, default_context="Ratings Scraper")
        # Position floating in the bottom-right corner over the content pane (starts minimized)
        margin = 30
        self.agent.setGeometry(950 - 180 - margin, 800 - 42 - margin, 180, 42)
        
        # Connect tab switches to update Agent's context dynamically
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep floating agent anchored to bottom-right corner during window resizes
        if hasattr(self, 'agent') and self.agent:
            margin = 30
            w = self.width()
            h = self.height()
            self.agent.move(w - self.agent.width() - margin, h - self.agent.height() - margin)

    def _on_tab_changed(self, index):
        tab_names = ["Ratings Scraper", "God Mode", "Universal Scraper", "Bulk OCM Generator"]
        name = tab_names[index] if index < len(tab_names) else "Agent Workspace"
        if hasattr(self, 'agent') and self.agent:
            self.agent.default_context = name
            self.agent.title_lbl.setText(f"Antigravity Agent ({name})")
            self.agent.chat_display.append(f"\n🤖 [Context Switch]: Switched context to {name}. Deep research button is fully mapped to feed resolved links into this workspace!")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files and files[0].endswith('.csv'):
            current_idx = self.tabs.currentIndex()
            # If user is on the Bulk OCM Generator tab, forward the CSV there
            if current_idx == 3:
                ocm_tab = self.tabs.widget(3)
                if hasattr(ocm_tab, 'load_csv'):
                    ocm_tab.load_csv(files[0])
            else:
                # Default: Forward CSV to the Ratings Scraper tab (tab index 0)
                ratings_tab = self.tabs.widget(0)
                if hasattr(ratings_tab, 'load_csv'):
                    ratings_tab.load_csv(files[0])


def main():
    parser = argparse.ArgumentParser(description="Hotel Data Tools")
    parser.add_argument('--csv', type=str, help='Path to a CSV file to load on launch')
    parser.add_argument('--workers', type=int, default=10,
                        help='Number of parallel workers (default: 10)')
    args, _ = parser.parse_known_args()

    app = QApplication(sys.argv)
    window = MainWindow(csv_path=args.csv, workers=args.workers)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
