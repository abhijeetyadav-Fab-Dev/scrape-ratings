# RatingsScraper — Plug & Play Guide

## ▶️ How to Run (Zero Setup Required)

### First Time on a New Machine
1. **Copy the entire `scrape-ratings` folder** to the Desktop (or anywhere)
2. **Double-click `INSTALL_AND_RUN.bat`**
3. That's it — it will automatically:
   - ✅ Install Python 3.11 (if not present)
   - ✅ Install all required packages
   - ✅ Download Chromium browser engine (~150MB, one-time)
   - ✅ Launch the app

> ⏱ First run takes **3–5 minutes**. Every run after that is instant.

---

### Every Time After (Already Set Up)
- **Double-click `START.bat`** — launches immediately

---

## 📁 Files Overview

| File | Purpose |
|------|---------|
| `INSTALL_AND_RUN.bat` | ⬅️ **First time only** — installs everything + launches |
| `START.bat` | ⬅️ **Every day use** — quick launcher |
| `BUILD_EXE.bat` | Builds a standalone `.exe` (for distribution) |
| `app.py` | Main application entry point |
| `dist/RatingsScraper.exe` | Pre-built standalone EXE (if available) |

---

## 💡 Want a True Single EXE?

If you want to share a single `.exe` file that needs zero setup:

1. Run `BUILD_EXE.bat` **on your machine** (takes 3–5 min)
2. Share `dist\RatingsScraper.exe` — it runs on any Windows PC with no Python needed

> ⚠️ The EXE will be ~200–300MB because it bundles Python + all libraries

---

## 🔧 Requirements (Handled Automatically)

- Windows 10/11 (64-bit)
- Internet connection on first run (to download Python + browser)
- ~500MB free disk space

All Python packages installed automatically:
- PyQt6, Playwright, httpx, pandas, beautifulsoup4, openpyxl, lxml, aiofiles

---

## ❓ Troubleshooting

**App doesn't open after install?**
→ Delete `.setup_complete` file and run `INSTALL_AND_RUN.bat` again

**"Python not found" after install?**
→ Restart your PC and run `START.bat` again (PATH needs refresh)

**Browser errors?**
→ Run this in Command Prompt: `python -m playwright install chromium`
