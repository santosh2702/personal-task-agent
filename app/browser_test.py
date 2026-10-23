from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir="./chrome_profile",
        channel="chrome",
        headless=False,
    )

    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://www.youtube.com")

    input("Press Enter to close the browser...")
    context.close()