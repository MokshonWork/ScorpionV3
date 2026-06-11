"""One-off probe for AmbitionBox page structure."""
import json
import re
import time

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def main():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--log-level=3")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    try:
        url = "https://www.ambitionbox.com/overview/tcs-overview"
        driver.get(url)
        time.sleep(6)
        print("title:", driver.title)
        print("url:", driver.current_url)
        src = driver.page_source
        print("html_len:", len(src))

        soup = BeautifulSoup(src, "html.parser")
        h1 = soup.find("h1")
        print("h1:", h1.get_text(strip=True)[:120] if h1 else None)

        nd = soup.find("script", id="__NEXT_DATA__")
        if nd and nd.string:
            data = json.loads(nd.string)
            print("next_keys:", list(data.keys()))
            props = data.get("props", {}).get("pageProps", {})
            print("pageProps_keys:", list(props.keys())[:30])
            with open("probe_next_data.json", "w", encoding="utf-8") as f:
                json.dump(props, f, indent=2, ensure_ascii=False)
            print("wrote probe_next_data.json")

        apis = set(re.findall(r"https?://[^\s\"']+", src))
        api_hits = [a for a in apis if "api" in a.lower() or "services" in a.lower()]
        for a in sorted(api_hits)[:20]:
            print("url_in_page:", a[:150])

        # Try reviews page
        driver.get("https://www.ambitionbox.com/reviews/tcs-reviews")
        time.sleep(6)
        print("\nreviews title:", driver.title)
        soup2 = BeautifulSoup(driver.page_source, "html.parser")
        nd2 = soup2.find("script", id="__NEXT_DATA__")
        if nd2 and nd2.string:
            data2 = json.loads(nd2.string)
            props2 = data2.get("props", {}).get("pageProps", {})
            print("reviews pageProps_keys:", list(props2.keys())[:40])
            with open("probe_reviews_next.json", "w", encoding="utf-8") as f:
                json.dump(props2, f, indent=2, ensure_ascii=False)
            print("wrote probe_reviews_next.json")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
