import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="FoodLink Sentinel Mock Server")

cache_requests_count = 0

@app.get("/sentinel-cache")
async def get_cache():
    global cache_requests_count
    cache_requests_count += 1
    # Serve a cached token value. Under shared cache settings, the client will
    # serve the cached value from memory/disk without requesting the server again.
    return JSONResponse(
        content={"token": f"cache-val-{cache_requests_count}"},
        headers={
            "Cache-Control": "public, max-age=3600",
            "ETag": f"cache-etag-{cache_requests_count}"
        }
    )

@app.get("/reset-cache")
async def reset_cache():
    global cache_requests_count
    cache_requests_count = 0
    return {"status": "ok", "message": "Cache counter reset to 0"}

@app.get("/sentinel-test-page", response_class=HTMLResponse)
async def get_test_page():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FoodLink Sentinel Test Page</title>
        <style>
            body { font-family: sans-serif; padding: 20px; background: #fafafa; }
            .box { padding: 15px; margin: 10px 0; border: 1px solid #ccc; background: white; border-radius: 5px; }
            h3 { margin-top: 0; }
        </style>
    </head>
    <body>
        <h1>Sentinel Isolation Test Page</h1>
        <div class="box">
            <h3>Cookies</h3>
            <div id="cookies"></div>
        </div>
        <div class="box">
            <h3>Local Storage</h3>
            <div id="local-storage"></div>
        </div>
        <div class="box">
            <h3>Session Storage</h3>
            <div id="session-storage"></div>
        </div>
        <div class="box">
            <h3>Cache Token</h3>
            <div id="cache-token">loading...</div>
        </div>
        <div class="box">
            <h3>Geolocation</h3>
            <div id="geo-status">Determining...</div>
            <div id="geo-coords">Lat: <span id="geo-lat"></span>, Lon: <span id="geo-lon"></span></div>
        </div>

        <script>
            // Render cookies
            document.getElementById('cookies').innerText = document.cookie;

            // Render LocalStorage keys
            document.getElementById('local-storage').innerText = JSON.stringify(Object.keys(localStorage));

            // Render SessionStorage keys
            document.getElementById('session-storage').innerText = JSON.stringify(Object.keys(sessionStorage));

            // Fetch cache token
            fetch('/sentinel-cache')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('cache-token').innerText = data.token;
                })
                .catch(err => {
                    document.getElementById('cache-token').innerText = 'error: ' + err.message;
                });

            // Get Geolocation
            navigator.geolocation.getCurrentPosition(
                (pos) => {
                    document.getElementById('geo-status').innerText = 'Success';
                    document.getElementById('geo-lat').innerText = pos.coords.latitude;
                    document.getElementById('geo-lon').innerText = pos.coords.longitude;
                },
                (err) => {
                    document.getElementById('geo-status').innerText = 'Error: ' + err.message + ' (Code ' + err.code + ')';
                },
                { enableHighAccuracy: true, timeout: 5000, maximumAge: 0 }
            );
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("SENTINEL_HOST", "localhost")
    port = int(os.getenv("SENTINEL_PORT", 8080))
    uvicorn.run(app, host=host, port=port)
