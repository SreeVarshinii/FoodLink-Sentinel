import asyncio
import re
from db import log_leakage_event

class AppMemoryRegistry:
    # Class-level variable to simulate shared application memory
    current_agent_token = None
    seen_cache_tokens = {}  # Map run_id -> set of cache tokens observed

def get_expected_coords(agent_idx: int):
    # Washington, DC base with increments based on agent index
    lat = 38.9072 + (agent_idx * 0.01)
    lon = -77.0369 - (agent_idx * 0.01)
    return lat, lon

async def inject_sentinels(page, context, agent_idx: int, config_name: str):
    """
    Injects unique sentinel tokens for the given agent index.
    """
    agent_id = f"agent_{agent_idx}"
    
    # 1. Inject Cookies
    await context.add_cookies([{
        "name": f"sentinel-cookie-{agent_id}",
        "value": f"cookie-{agent_id}",
        "domain": "localhost",
        "path": "/"
    }])
    
    # 2. Inject Local Storage & Session Storage via init script
    # This runs before the page load script executes.
    await context.add_init_script(f"""
        window.localStorage.setItem('sentinel-local-storage-{agent_id}', 'storage-{agent_id}');
        window.sessionStorage.setItem('sentinel-session-storage-{agent_id}', 'session-{agent_id}');
    """)
    
    # 3. Inject App Memory
    AppMemoryRegistry.current_agent_token = f"mem-{agent_id}"

async def validate_leakage(page, context, agent_idx: int, config_name: str, run_id: str, expected_cache_num: int):
    """
    Validates if any cross-agent sentinel tokens are visible.
    Logs leaks directly to the database.
    Returns: (num_leaks, list_of_leaks)
    """
    agent_id = f"agent_{agent_idx}"
    leaks = []
    
    # Wait for the page JS to finish updating fields
    await asyncio.sleep(1.0)
    
    # --- 1. Cookie Leak Check ---
    cookies = await context.cookies("http://localhost:8080")
    for cookie in cookies:
        name = cookie["name"]
        match = re.match(r"sentinel-cookie-agent_(\d+)", name)
        if match:
            observed_idx = int(match.group(1))
            if observed_idx != agent_idx:
                leaks.append({
                    "leak_type": "cookie",
                    "expected_token": f"cookie-agent_{agent_idx}",
                    "observed_token": f"cookie-agent_{observed_idx}",
                    "severity": "high"
                })

    # --- 2. Local Storage Leak Check ---
    try:
        ls_keys = await page.evaluate("Object.keys(localStorage)")
        for key in ls_keys:
            match = re.match(r"sentinel-local-storage-agent_(\d+)", key)
            if match:
                observed_idx = int(match.group(1))
                if observed_idx != agent_idx:
                    leaks.append({
                        "leak_type": "local_storage",
                        "expected_token": f"storage-agent_{agent_idx}",
                        "observed_token": f"storage-agent_{observed_idx}",
                        "severity": "high"
                    })
    except Exception as e:
        print(f"Error checking localStorage for Agent {agent_idx}: {e}")

    # --- 3. Session Storage Leak Check ---
    try:
        ss_keys = await page.evaluate("Object.keys(sessionStorage)")
        for key in ss_keys:
            match = re.match(r"sentinel-session-storage-agent_(\d+)", key)
            if match:
                observed_idx = int(match.group(1))
                if observed_idx != agent_idx:
                    leaks.append({
                        "leak_type": "session_storage",
                        "expected_token": f"session-agent_{agent_idx}",
                        "observed_token": f"session-agent_{observed_idx}",
                        "severity": "medium"
                    })
    except Exception as e:
        print(f"Error checking sessionStorage for Agent {agent_idx}: {e}")

    # --- 4. Cache Leak Check ---
    try:
        cache_token_text = await page.locator("#cache-token").text_content()
        cache_token_text = cache_token_text.strip()
        
        # Ensure we have a set for this run_id + config_name
        cache_key = f"{run_id}_{config_name}"
        if cache_key not in AppMemoryRegistry.seen_cache_tokens:
            AppMemoryRegistry.seen_cache_tokens[cache_key] = set()
            
        if cache_token_text in AppMemoryRegistry.seen_cache_tokens[cache_key]:
            # This cache token has already been seen by a different agent in the same run!
            leaks.append({
                "leak_type": "cache",
                "expected_token": "unique-cache-response",
                "observed_token": cache_token_text,
                "severity": "medium"
            })
        else:
            AppMemoryRegistry.seen_cache_tokens[cache_key].add(cache_token_text)
    except Exception as e:
        print(f"Error checking cache for Agent {agent_idx}: {e}")

    # --- 5. Geolocation Leak Check ---
    try:
        lat_text = await page.locator("#geo-lat").text_content()
        lon_text = await page.locator("#geo-lon").text_content()
        if lat_text and lon_text:
            lat = float(lat_text)
            lon = float(lon_text)
            
            # Find which agent index matches these coordinates
            # Check up to 50 agents
            matched_idx = None
            for j in range(1, 55):
                exp_lat, exp_lon = get_expected_coords(j)
                if abs(lat - exp_lat) < 1e-4 and abs(lon - exp_lon) < 1e-4:
                    matched_idx = j
                    break
            
            if matched_idx is not None and matched_idx != agent_idx:
                leaks.append({
                    "leak_type": "geolocation",
                    "expected_token": f"geo-agent_{agent_idx}",
                    "observed_token": f"geo-agent_{matched_idx}",
                    "severity": "medium"
                })
    except Exception as e:
        print(f"Error checking geolocation for Agent {agent_idx}: {e}")

    # --- 6. Application Memory Leak Check ---
    # We yield control for other concurrent tasks, then check if our shared state got clobbered
    await asyncio.sleep(0.1)
    expected_mem = f"mem-agent_{agent_idx}"
    if AppMemoryRegistry.current_agent_token != expected_mem:
        # Clashed with another agent index
        observed_token = AppMemoryRegistry.current_agent_token or "None"
        observed_match = re.match(r"mem-agent_(\d+)", observed_token)
        observed_idx = observed_match.group(1) if observed_match else "unknown"
        
        leaks.append({
            "leak_type": "app_memory",
            "expected_token": f"mem-agent_{agent_idx}",
            "observed_token": f"{observed_token}",
            "severity": "high"
        })

    # Log leaks to SQLite database
    for leak in leaks:
        log_leakage_event(
            run_id=run_id,
            agent_id=agent_id,
            leak_type=leak["leak_type"],
            expected_token=leak["expected_token"],
            observed_token=leak["observed_token"],
            domain="localhost",
            severity=leak["severity"]
        )
        
    return len(leaks), leaks
