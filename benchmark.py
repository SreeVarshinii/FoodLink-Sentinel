import asyncio
import os
import time
import psutil
import urllib.request
from datetime import datetime
import pandas as pd
from playwright.async_api import async_playwright

from db import init_db, save_benchmark_result
from sentinel import inject_sentinels, validate_leakage, get_expected_coords

def reset_server_cache():
    try:
        url = "http://localhost:8080/reset-cache"
        with urllib.request.urlopen(url) as response:
            pass
    except Exception as e:
        print(f"[Benchmark] Warning: Could not reset server cache: {e}")

def get_process_memory_mb():
    """
    Get RSS memory of python process and all its children browser processes in MB.
    """
    try:
        current_process = psutil.Process()
        total_mem = current_process.memory_info().rss
        for child in current_process.children(recursive=True):
            try:
                total_mem += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total_mem / (1024 * 1024)
    except Exception:
        return 0

class MemoryMonitor:
    def __init__(self, interval=0.1):
        self.interval = interval
        self.peak_mem = 0
        self.running = False
        self.task = None

    async def start(self):
        self.running = True
        self.peak_mem = get_process_memory_mb()
        self.task = asyncio.create_task(self._monitor())

    async def _monitor(self):
        while self.running:
            mem = get_process_memory_mb()
            if mem > self.peak_mem:
                self.peak_mem = mem
            await asyncio.sleep(self.interval)

    async def stop(self):
        self.running = False
        if self.task:
            await self.task
        return self.peak_mem

async def run_config_a(run_id, num_agents, p):
    """
    Config A: Shared Page.
    All agents run concurrently on a single browser tab.
    Expected: Extreme race conditions, navigation failures.
    """
    print(f"\n[Config A] Starting benchmark with {num_agents} agents...")
    browser = await p.chromium.launch(headless=True)
    # One context, one page
    context = await browser.new_context(
        permissions=["geolocation"],
        geolocation={"latitude": 38.9072, "longitude": -77.0369}
    )
    page = await context.new_page()
    
    latencies = []
    success_count = 0
    agents_with_leaks = 0
    
    async def run_agent(idx):
        nonlocal success_count, agents_with_leaks
        await asyncio.sleep(0.5 * (idx - 1))
        
        # Overwrite geolocation
        lat, lon = get_expected_coords(idx)
        await context.set_geolocation({"latitude": lat, "longitude": lon})
        
        await inject_sentinels(page, context, idx, "Config_A")
        
        start_time = time.time()
        try:
            # Expect many errors due to concurrent page.goto
            await page.goto("http://localhost:8080/sentinel-test-page", timeout=8000)
            latency = time.time() - start_time
            latencies.append(latency)
            success_count += 1
            
            num_leaks, leaks = await validate_leakage(page, context, idx, "Config_A", run_id, idx)
            browser_leaks = [l for l in leaks if l["leak_type"] != "app_memory"]
            if len(browser_leaks) > 0:
                agents_with_leaks += 1
        except Exception as e:
            # Expected concurrency error
            pass
            
    tasks = [run_agent(i) for i in range(1, num_agents + 1)]
    await asyncio.gather(*tasks)
    
    await context.close()
    await browser.close()
    
    return latencies, success_count, agents_with_leaks

async def run_config_b(run_id, num_agents, p):
    """
    Config B: Separate Pages, Shared Context.
    Each agent runs in a new tab, sharing storage, cookies, and cache.
    Expected: Cache and Storage leakages.
    """
    print(f"\n[Config B] Starting benchmark with {num_agents} agents...")
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context(
        permissions=["geolocation"],
        geolocation={"latitude": 38.9072, "longitude": -77.0369}
    )
    
    latencies = []
    success_count = 0
    agents_with_leaks = 0
    
    async def run_agent(idx):
        nonlocal success_count, agents_with_leaks
        await asyncio.sleep(0.5 * (idx - 1))
        page = await context.new_page()
        
        # Overwrite context geolocation (clobbers other pages)
        lat, lon = get_expected_coords(idx)
        await context.set_geolocation({"latitude": lat, "longitude": lon})
        
        await inject_sentinels(page, context, idx, "Config_B")
        
        start_time = time.time()
        try:
            await page.goto("http://localhost:8080/sentinel-test-page", timeout=10000)
            latency = time.time() - start_time
            latencies.append(latency)
            success_count += 1
            
            num_leaks, leaks = await validate_leakage(page, context, idx, "Config_B", run_id, idx)
            browser_leaks = [l for l in leaks if l["leak_type"] != "app_memory"]
            if len(browser_leaks) > 0:
                agents_with_leaks += 1
        except Exception as e:
            print(f"Agent {idx} failed: {e}")
        finally:
            await page.close()
            
    tasks = [run_agent(i) for i in range(1, num_agents + 1)]
    await asyncio.gather(*tasks)
    
    await context.close()
    await browser.close()
    
    return latencies, success_count, agents_with_leaks

async def run_config_c(run_id, num_agents, p):
    """
    Config C: Isolated Browser Contexts.
    Each agent has a separate context and page in one browser instance.
    Expected: Strong isolation, low resource overhead.
    """
    print(f"\n[Config C] Starting benchmark with {num_agents} agents...")
    browser = await p.chromium.launch(headless=True)
    
    latencies = []
    success_count = 0
    agents_with_leaks = 0
    
    async def run_agent(idx):
        nonlocal success_count, agents_with_leaks
        await asyncio.sleep(0.5 * (idx - 1))
        lat, lon = get_expected_coords(idx)
        context = await browser.new_context(
            permissions=["geolocation"],
            geolocation={"latitude": lat, "longitude": lon},
            service_workers="block"
        )
        page = await context.new_page()
        
        await inject_sentinels(page, context, idx, "Config_C")
        
        start_time = time.time()
        try:
            await page.goto("http://localhost:8080/sentinel-test-page", timeout=12000)
            latency = time.time() - start_time
            latencies.append(latency)
            success_count += 1
            
            num_leaks, leaks = await validate_leakage(page, context, idx, "Config_C", run_id, idx)
            browser_leaks = [l for l in leaks if l["leak_type"] != "app_memory"]
            if len(browser_leaks) > 0:
                agents_with_leaks += 1
        except Exception as e:
            print(f"Agent {idx} failed: {e}")
        finally:
            await context.close()
            
    tasks = [run_agent(i) for i in range(1, num_agents + 1)]
    await asyncio.gather(*tasks)
    
    await browser.close()
    
    return latencies, success_count, agents_with_leaks

async def run_config_d(run_id, num_agents, p):
    """
    Config D: Isolated Browser Processes.
    Each agent starts a fresh chromium browser instance.
    Expected: Highest isolation, high memory usage and startup delay.
    """
    print(f"\n[Config D] Starting benchmark with {num_agents} agents...")
    
    latencies = []
    success_count = 0
    agents_with_leaks = 0
    
    async def run_agent(idx):
        nonlocal success_count, agents_with_leaks
        await asyncio.sleep(0.5 * (idx - 1))
        browser = await p.chromium.launch(headless=True)
        lat, lon = get_expected_coords(idx)
        context = await browser.new_context(
            permissions=["geolocation"],
            geolocation={"latitude": lat, "longitude": lon},
            service_workers="block"
        )
        page = await context.new_page()
        
        await inject_sentinels(page, context, idx, "Config_D")
        
        start_time = time.time()
        try:
            await page.goto("http://localhost:8080/sentinel-test-page", timeout=15000)
            latency = time.time() - start_time
            latencies.append(latency)
            success_count += 1
            
            num_leaks, leaks = await validate_leakage(page, context, idx, "Config_D", run_id, idx)
            browser_leaks = [l for l in leaks if l["leak_type"] != "app_memory"]
            if len(browser_leaks) > 0:
                agents_with_leaks += 1
        except Exception as e:
            print(f"Agent {idx} failed: {e}")
        finally:
            await context.close()
            await browser.close()
            
    tasks = [run_agent(i) for i in range(1, num_agents + 1)]
    await asyncio.gather(*tasks)
    
    return latencies, success_count, agents_with_leaks

async def run_experiment_suite(num_agents=10, run_id=None):
    """
    Runs the benchmark suite under all 4 configs and records results.
    Automatically starts the local FastAPI server if not running.
    """
    init_db()
    if not run_id:
        run_id = f"run_{datetime.now().strftime('%Y_%m_%d_%H%M%S')}"
        
    print(f"=== Starting Benchmark Suite (ID: {run_id}) with {num_agents} agents ===")
    
    # Check if local server is running, if not start it
    import subprocess
    import sys
    import urllib.request
    
    server_process = None
    server_running = False
    try:
        url = "http://localhost:8080/sentinel-test-page"
        with urllib.request.urlopen(url, timeout=1) as response:
            server_running = True
    except Exception:
        pass
        
    if not server_running:
        print("[Benchmark] Local FastAPI server not detected. Launching server.py in background...")
        # Use python from venv if present, otherwise system python
        python_exec = os.path.join("venv", "bin", "python")
        if not os.path.exists(python_exec):
            python_exec = sys.executable
        server_process = subprocess.Popen(
            [python_exec, "server.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await asyncio.sleep(3) # Wait for server to bind
        
    configs = [
        ("Shared Page", run_config_a),
        ("Shared Context", run_config_b),
        ("New Context", run_config_c),
        ("New Process", run_config_d)
    ]
    
    suite_results = []
    
    try:
        async with async_playwright() as p:
            for name, run_func in configs:
                reset_server_cache()
                baseline_mem = get_process_memory_mb()
                
                # Start memory monitor
                monitor = MemoryMonitor()
                await monitor.start()
                
                start_time = time.time()
                try:
                    latencies, success, leak_count = await run_func(run_id, num_agents, p)
                except Exception as e:
                    print(f"Error running configuration {name}: {e}")
                    latencies, success, leak_count = [], 0, 0
                    
                elapsed = time.time() - start_time
                peak_mem = await monitor.stop()
                
                # Compute metrics
                completion_rate = (success / num_agents) * 100
                leakage_rate = (leak_count / num_agents) * 100
                
                # Median latency
                if latencies:
                    latencies.sort()
                    median_lat = latencies[len(latencies)//2]
                else:
                    median_lat = elapsed
                    
                # Delta memory in MB per agent
                mem_used_total = peak_mem - baseline_mem
                mem_per_agent = max(0.0, mem_used_total / num_agents)
                
                print(f"[{name}] Results: Leakage Rate: {leakage_rate}%, Completion: {completion_rate}%, Latency: {median_lat:.2f}s, Memory: {mem_per_agent:.2f}MB")
                
                save_benchmark_result(
                    run_id=run_id,
                    config_name=name,
                    leakage_rate=leakage_rate,
                    completion_rate=completion_rate,
                    median_latency=median_lat,
                    memory_per_agent=mem_per_agent,
                    max_concurrency=num_agents
                )
                
                suite_results.append({
                    "config_name": name,
                    "leakage_rate": leakage_rate,
                    "completion_rate": completion_rate,
                    "median_latency": median_lat,
                    "memory_per_agent": mem_per_agent
                })
                
                # Small cooldown
                await asyncio.sleep(2)
    finally:
        if server_process:
            print("[Benchmark] Stopping background FastAPI server...")
            server_process.terminate()
            server_process.wait()
            print("[Benchmark] Server stopped.")
            
    print("\nBenchmark Suite Completed.")
    return suite_results

if __name__ == "__main__":
    asyncio.run(run_experiment_suite(num_agents=10))
