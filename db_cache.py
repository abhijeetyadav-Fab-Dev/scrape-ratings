import sqlite3
import json
import time
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "scraper_cache.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Ratings cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings_cache (
            key TEXT PRIMARY KEY,
            rating REAL,
            review_count INTEGER,
            scraped_source TEXT,
            timestamp REAL
        )
    """)
    
    # 2. Parallel Finder cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parallel_finder_cache (
            key TEXT PRIMARY KEY,
            results_json TEXT,
            timestamp REAL
        )
    """)
    
    # 3. Batch runs state (for resumable runs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS batch_runs (
            run_id TEXT PRIMARY KEY,
            input_file TEXT,
            current_index INTEGER,
            total_items INTEGER,
            status TEXT,
            output_file TEXT,
            timestamp REAL
        )
    """)
    
    conn.commit()
    conn.close()

# Initialize DB on import
init_db()

# Cache Accessors
def get_cached_rating(platform, identifier):
    """
    Get cached rating.
    identifier can be a URL, hotel name, etc.
    """
    key = f"{platform}:{identifier.strip().lower()}"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT rating, review_count, scraped_source, timestamp FROM ratings_cache WHERE key = ?",
        (key,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        # Check cache expiry (e.g., 7 days = 604800 seconds)
        if time.time() - row['timestamp'] < 604800:
            return {
                'rating': row['rating'],
                'review_count': row['review_count'],
                'scraped_source': row['scraped_source']
            }
    return None

def set_cached_rating(platform, identifier, rating, review_count, scraped_source):
    key = f"{platform}:{identifier.strip().lower()}"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO ratings_cache (key, rating, review_count, scraped_source, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (key, rating, review_count, scraped_source, time.time())
    )
    conn.commit()
    conn.close()

def get_cached_parallel_finder(query, lat, lng):
    """
    Get cached parallel finder results.
    """
    key = f"{query.strip().lower()}:{lat}:{lng}"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT results_json, timestamp FROM parallel_finder_cache WHERE key = ?",
        (key,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        # Cache for parallel finder can live longer, e.g. 14 days
        if time.time() - row['timestamp'] < 1209600:
            try:
                return json.loads(row['results_json'])
            except Exception:
                return None
    return None

def set_cached_parallel_finder(query, lat, lng, results):
    key = f"{query.strip().lower()}:{lat}:{lng}"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO parallel_finder_cache (key, results_json, timestamp)
        VALUES (?, ?, ?)
        """,
        (key, json.dumps(results), time.time())
    )
    conn.commit()
    conn.close()

# Batch run state tracking
def update_batch_run(run_id, input_file, current_index, total_items, status, output_file):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO batch_runs (run_id, input_file, current_index, total_items, status, output_file, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, input_file, current_index, total_items, status, output_file, time.time())
    )
    conn.commit()
    conn.close()

def get_batch_run(run_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT input_file, current_index, total_items, status, output_file FROM batch_runs WHERE run_id = ?",
        (run_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_all_batch_runs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT run_id, input_file, current_index, total_items, status, output_file, timestamp FROM batch_runs ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def clear_all_caches():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ratings_cache")
    cursor.execute("DELETE FROM parallel_finder_cache")
    cursor.execute("DELETE FROM batch_runs")
    conn.commit()
    conn.close()

def get_cache_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM ratings_cache")
    ratings_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM parallel_finder_cache")
    finder_count = cursor.fetchone()[0]
    conn.close()
    return {
        'ratings_cached': ratings_count,
        'finder_cached': finder_count
    }
