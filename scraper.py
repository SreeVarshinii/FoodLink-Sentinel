import os
import asyncio
import re
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import google.generativeai as genai
from playwright.async_api import async_playwright

load_dotenv()

# Configure Gemini API if available
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HAS_LLM = False
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        HAS_LLM = True
    except Exception as e:
        print(f"Error configuring Gemini API: {e}. Falling back to rule-based parser.")

# Pydantic schema for structured output
class PantryData(BaseModel):
    hours: str = Field(description="Operational hours or days open (e.g. 'Saturdays 9am-12pm')")
    donation_needs: str = Field(description="Items currently needed for donations (e.g. 'Canned food, cereal')")
    volunteer_slots: str = Field(description="Volunteer opportunities or signup instructions")

# Source Registry of DMV Food Banks/Pantries (from sources.csv and prompt)
SOURCE_REGISTRY = [
    {
        "name": "Maryland Food Bank",
        "url": "https://mdfoodbank.org/find-food/",
        "zip_code": "21227",
        "latitude": 39.2227,
        "longitude": -76.6811,
        "task": "Find food assistance hours and donation details"
    },
    {
        "name": "Anne Arundel County Food Bank",
        "url": "https://aafoodbank.org/",
        "zip_code": "21032",
        "latitude": 39.0270,
        "longitude": -76.6212,
        "task": "Check community pantry operating hours and food needs"
    },
    {
        "name": "SPAN (Serving People Across Neighborhoods)",
        "url": "https://www.spanhelps.org/",
        "zip_code": "21146",
        "latitude": 39.0768,
        "longitude": -76.5678,
        "task": "Find Saturday pantry hours and current food pantry needs"
    },
    {
        "name": "Capital Area Food Bank",
        "url": "https://www.capitalareafoodbank.org/",
        "zip_code": "20017",
        "latitude": 38.9377,
        "longitude": -76.9947,
        "task": "Get partner distribution site finder details and volunteer slots"
    },
    {
        "name": "Manna Food Center",
        "url": "https://www.mannafood.org/",
        "zip_code": "20850",
        "latitude": 39.0840,
        "longitude": -77.1528,
        "task": "Find food pickup schedules and volunteer instructions"
    },
    {
        "name": "Caroline County Food Pantries",
        "url": "https://carolinebettertogether.org/food-pantries",
        "zip_code": "21629",
        "latitude": 38.9137,
        "longitude": -75.8277,
        "task": "Locate local food pantries list and schedule details"
    },
    {
        "name": "PG County Food Pantry Resources",
        "url": "https://pgcfec.org/resources/find-food-food-pantry-listings/",
        "zip_code": "20743",
        "latitude": 38.8911,
        "longitude": -76.9077,
        "task": "Extract find food list, phone numbers, and volunteer contact"
    }
]

def fallback_extract(html_content: str, url: str) -> PantryData:
    """
    Fallback parser using BeautifulSoup and regex rules to extract data
    if no LLM API key is present.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Strip scripts and styles
    for script in soup(["script", "style"]):
        script.decompose()
        
    text = soup.get_text(separator=' ')
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # 1. Extract Hours
    hours_match = []
    # Look for sentences/bullet points containing days of week or times
    lines = [line.strip() for line in text.split('.') if len(line.strip()) > 5]
    for line in lines:
        if any(day in line.lower() for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'weekdays', 'hours:']):
            if any(time_keyword in line.lower() for time_keyword in ['am', 'pm', 'clock', 'open', 'close', 'schedule', 'time']):
                hours_match.append(line)
                if len(hours_match) >= 3:
                    break
                    
    hours = ". ".join(hours_match) if hours_match else "Hours details not clearly specified. Please visit site."
    if len(hours) > 300:
        hours = hours[:297] + "..."
        
    # 2. Extract Donation Needs
    needs_match = []
    # Search for lists or sections with donation needs
    for tag in soup.find_all(['li', 'p', 'h2', 'h3', 'h4']):
        tag_text = tag.get_text().strip()
        if any(keyword in tag_text.lower() for keyword in ['canned', 'peanut butter', 'non-perishable', 'donations needed', 'needs:', 'accepting', 'food drive', 'items list']):
            if len(tag_text) > 10 and len(tag_text) < 150:
                needs_match.append(tag_text)
                if len(needs_match) >= 4:
                    break
                    
    donation_needs = ", ".join(needs_match) if needs_match else "Canned goods, non-perishable foods, hygiene items. Check website to confirm."
    if len(donation_needs) > 300:
        donation_needs = donation_needs[:297] + "..."
        
    # 3. Extract Volunteer Slots
    vol_match = []
    for tag in soup.find_all(['a', 'p', 'li']):
        tag_text = tag.get_text().strip()
        if any(keyword in tag_text.lower() for keyword in ['volunteer opportunities', 'sign up to volunteer', 'volunteer registration', 'volunteer shifts', 'become a volunteer']):
            if len(tag_text) > 15 and len(tag_text) < 200:
                vol_match.append(tag_text)
                if len(vol_match) >= 3:
                    break
                    
    volunteer_slots = ". ".join(vol_match) if vol_match else "Volunteer registration available online. Visit site/signup link."
    if len(volunteer_slots) > 300:
        volunteer_slots = volunteer_slots[:297] + "..."
        
    return PantryData(
        hours=hours,
        donation_needs=donation_needs,
        volunteer_slots=volunteer_slots
    )

def llm_extract(html_content: str, url: str) -> PantryData:
    """
    Advanced extractor using Gemini API structured output.
    """
    # Clean text to fit in context window
    soup = BeautifulSoup(html_content, 'html.parser')
    for script in soup(["script", "style", "meta", "link"]):
        script.decompose()
    text = soup.get_text(separator=' ')
    cleaned_text = re.sub(r'\s+', ' ', text)[:8000] # Limit to 8k chars for token safety
    
    prompt = f"""
    You are an expert data extraction assistant. Analyze the text scraped from the website {url} and extract details about operational hours/days, donation needs, and volunteer slots.
    
    Raw text:
    {cleaned_text}
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=PantryData
            )
        )
        # Parse output into Pydantic schema
        data = PantryData.model_validate_json(response.text)
        return data
    except Exception as e:
        print(f"Gemini API generation failed: {e}. Falling back to rule-based parser.")
        return fallback_extract(html_content, url)

async def scrape_site(site: dict) -> dict:
    """
    Playwright agent that crawls a single food bank website and extracts normalized data.
    Uses Config C (Isolated Context) to avoid session leakage.
    """
    name = site["name"]
    url = site["url"]
    print(f"[Scraper] Starting Playwright agent for {name} ({url})...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use isolated context
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            service_workers="block"
        )
        page = await context.new_page()
        
        try:
            # Navigate with a 30s timeout
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000) # Give 2s for layout shift / client-render
            
            html_content = await page.content()
            
            # Extract content
            if HAS_LLM:
                data = llm_extract(html_content, url)
            else:
                data = fallback_extract(html_content, url)
                
            result = {
                "site_name": name,
                "url": url,
                "hours": data.hours,
                "donation_needs": data.donation_needs,
                "volunteer_slots": data.volunteer_slots,
                "latitude": site["latitude"],
                "longitude": site["longitude"],
                "zip_code": site["zip_code"],
                "status": "success"
            }
            print(f"[Scraper] Successfully scraped {name}!")
            return result
            
        except Exception as e:
            print(f"[Scraper] Error scraping {name}: {e}")
            return {
                "site_name": name,
                "url": url,
                "hours": "Error loading website.",
                "donation_needs": "Error loading website.",
                "volunteer_slots": "Error loading website.",
                "latitude": site["latitude"],
                "longitude": site["longitude"],
                "zip_code": site["zip_code"],
                "status": "failed",
                "error": str(e)
            }
        finally:
            await context.close()
            await browser.close()

async def run_production_scraper():
    """
    Runs scraping concurrently for all registered sources.
    """
    print(f"Starting production scraper for {len(SOURCE_REGISTRY)} sources...")
    tasks = [scrape_site(site) for site in SOURCE_REGISTRY]
    results = await asyncio.gather(*tasks)
    return results

async def scrape_and_save_all():
    """
    Scrapes all sources and commits successful/fallback records to SQLite.
    """
    from db import init_db, save_scraped_data
    init_db()
    results = await run_production_scraper()
    saved_count = 0
    for res in results:
        # Save results (even if failed, we record the error placeholder)
        save_scraped_data(
            site_name=res["site_name"],
            url=res["url"],
            hours=res["hours"],
            donation_needs=res["donation_needs"],
            volunteer_slots=res["volunteer_slots"],
            latitude=res["latitude"],
            longitude=res["longitude"],
            zip_code=res["zip_code"]
        )
        if res.get("status") == "success":
            saved_count += 1
    print(f"[Scraper] Saved {saved_count} successfully scraped food banks to database.")
    return results

if __name__ == "__main__":
    # Test script entry
    print("HAS_LLM API key:", HAS_LLM)
    async def test():
        # Test full scrape and save
        await scrape_and_save_all()
    asyncio.run(test())

