# FoodLink Sentinel (Lite)

**FoodLink Sentinel** is a dual-purpose platform combining an asynchronous web crawler that maps DMV-area food donation and volunteer sites with an isolation testbed for multi-agent browser systems.

---

## What the Project Does

### 1. Real-Time Resource Finder (Live Scraper)
* **Crawling & Normalization**: Runs parallel, isolated browser agents (using Playwright and `asyncio`) to scrape 7 DMV-area food bank and volunteer search engines.
* **Extraction Fallbacks**: Parses raw page HTML to extract operational hours, donation needs, and volunteer shift availabilities. Uses Gemini API (structured outputs) when configured, falling back to a CSS/regex rule-based parser.
* **Locator Search**: Provides a Streamlit frontend letting users search by ZIP code and radius. It computes great-circle distances using the Haversine equation and displays matching centers sorted by distance and date scraped.

### 2. Session Isolation Benchmark (Sentinel Methodology)
* **Sandboxed Testing**: Runs a local FastAPI server to simulate browser states (cookies, localStorage, session storage, caching, and geolocations) without rate-limiting or IP bans from live servers.
* **Sentinel Fingerprinting**: Issues each agent a unique synthetic identity (e.g., unique cookies and geolocations) before run, then validates if any agent can view or access another agent's session parameters post-run.
* **Isolation Profiles Comparison**: Evaluates and runs the exact workload under four configurations:
  1. **Shared Page (Config A)**: Concurrently sharing one page.
  2. **Shared Context (Config B)**: Reusing a single browser context across multiple tabs.
  3. **New Context (Config C)**: Separating contexts inside one browser.
  4. **New Process (Config D)**: Spawning a distinct Chromium process per agent.
* **Live Experimentation**: Records peak RAM delta using `psutil` alongside latencies and outputs a **Leakage Matrix** (PASS/FAIL) mapping cookie, local storage, cache, and geolocation leaks.
