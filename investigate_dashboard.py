import asyncio
from playwright.async_api import async_playwright
import sys

async def main():
    url = "http://localhost:8000"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto(url)
            await page.wait_for_load_state()
            
            # Take screenshot
            await page.screenshot(path="dashboard_initial.png")
            
            # Get console logs
            console_logs = []
            page.on("console", lambda msg: console_logs.append(msg.text))
            
            # Wait a bit for dynamic content
            await asyncio.sleep(3)
            
            # Take another screenshot after content loads
            await page.screenshot(path="dashboard_loaded.png")
            
            # Check for specific elements
            mod_list = await page.query_selector("#mod-list")
            mod_list_exists = bool(mod_list)
            
            tabs = await page.query_selector_all(".tab")
            tabs_count = len(tabs)
            
            # Get network responses
            network_requests = []
            page.on("request", lambda req: network_requests.append(req.url))
            page.on("response", lambda res: network_requests.append(f"RESPONSE: {res.url()}"))
            
            # Get page title
            title = await page.title()
            
            # Get HTML content
            html = await page.content()
            
            # Check for JavaScript errors
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            
            # Print results
            print(f"Page title: {title}")
            print(f"Mod list element exists: {mod_list_exists}")
            print(f"Number of tabs found: {tabs_count}")
            print(f"Console logs: {console_logs}")
            print(f"JavaScript errors: {errors}")
            print(f"Network requests: {network_requests[:10]}...")
            
            # Save detailed info
            with open("dashboard_report.txt", "w") as f:
                f.write(f"Title: {title}\n")
                f.write(f"Mod list exists: {mod_list_exists}\n")
                f.write(f"Tabs count: {tabs_count}\n")
                f.write(f"Console logs: {console_logs}\n")
                f.write(f"JavaScript errors: {errors}\n")
                f.write(f"HTML content: {html[:1000]}...")
                
            # Close browser
            await browser.close()
            
            print("Dashboard investigation completed successfully!")
            
        except Exception as e:
            print(f"Error investigating dashboard: {e}")
            await browser.close()
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())