from playwright.sync_api import sync_playwright

def play_on_youtube(song: str):
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="./chrome_profile",
            channel="chrome",
            headless=False,
        )

        page = context.pages[0] if context.pages else context.new_page()

        # Open YouTube search results
        page.goto(
            f"https://www.youtube.com/results?search_query={song.replace(' ', '+')}"
        )

        print(f"Searching YouTube for: {song}")

        # Wait for video results
        page.locator("ytd-video-renderer a#video-title").first.wait_for(
            state="visible",
            timeout=20000,
        )

        # Click the first video
        page.locator("ytd-video-renderer a#video-title").first.click()

        print("Video opened. Playback may require user interaction.")

        input("Press Enter to close the browser...")
        context.close()


if __name__ == "__main__":
    song = input("Which song should I play? ")
    play_on_youtube(song)