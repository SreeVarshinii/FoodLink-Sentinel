import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "foodlink.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Scraped Data Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scraped_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_name TEXT UNIQUE,
        url TEXT,
        hours TEXT,
        donation_needs TEXT,
        volunteer_slots TEXT,
        latitude REAL,
        longitude REAL,
        zip_code TEXT,
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 2. Benchmark Results Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS benchmark_results (
        run_id TEXT,
        config_name TEXT,
        leakage_rate REAL,
        completion_rate REAL,
        median_latency REAL,
        memory_per_agent REAL,
        max_concurrency INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (run_id, config_name)
    )
    """)
    
    # 3. Leakage Events Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leakage_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        agent_id TEXT,
        leak_type TEXT,
        expected_token TEXT,
        observed_token TEXT,
        domain TEXT,
        severity TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()

def save_scraped_data(site_name, url, hours, donation_needs, volunteer_slots, latitude, longitude, zip_code):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO scraped_data (site_name, url, hours, donation_needs, volunteer_slots, latitude, longitude, zip_code, last_updated)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(site_name) DO UPDATE SET
        url = excluded.url,
        hours = excluded.hours,
        donation_needs = excluded.donation_needs,
        volunteer_slots = excluded.volunteer_slots,
        latitude = excluded.latitude,
        longitude = excluded.longitude,
        zip_code = excluded.zip_code,
        last_updated = CURRENT_TIMESTAMP
    """, (site_name, url, hours, donation_needs, volunteer_slots, latitude, longitude, zip_code))
    conn.commit()
    conn.close()

def get_all_scraped_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scraped_data ORDER BY site_name")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def save_benchmark_result(run_id, config_name, leakage_rate, completion_rate, median_latency, memory_per_agent, max_concurrency):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO benchmark_results (run_id, config_name, leakage_rate, completion_rate, median_latency, memory_per_agent, max_concurrency, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(run_id, config_name) DO UPDATE SET
        leakage_rate = excluded.leakage_rate,
        completion_rate = excluded.completion_rate,
        median_latency = excluded.median_latency,
        memory_per_agent = excluded.memory_per_agent,
        max_concurrency = excluded.max_concurrency,
        timestamp = CURRENT_TIMESTAMP
    """, (run_id, config_name, leakage_rate, completion_rate, median_latency, memory_per_agent, max_concurrency))
    conn.commit()
    conn.close()

def get_benchmark_results():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM benchmark_results ORDER BY timestamp DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def log_leakage_event(run_id, agent_id, leak_type, expected_token, observed_token, domain, severity):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO leakage_events (run_id, agent_id, leak_type, expected_token, observed_token, domain, severity, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (run_id, agent_id, leak_type, expected_token, observed_token, domain, severity))
    conn.commit()
    conn.close()

def get_leakage_events(run_id=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if run_id:
        cursor.execute("SELECT * FROM leakage_events WHERE run_id = ? ORDER BY timestamp DESC", (run_id,))
    else:
        cursor.execute("SELECT * FROM leakage_events ORDER BY timestamp DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

if __name__ == "__main__":
    init_db()
    print("Database initialized at", DB_PATH)
