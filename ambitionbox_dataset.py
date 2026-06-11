"""Build a company dataset from public AmbitionBox company pages.

The scraper collects company cards from the AmbitionBox listing pages and then
enriches each company from its overview page's embedded structured data.
"""
import argparse
import csv
import json
import os
import random
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.ambitionbox.com"
OUTPUT_DIR = os.path.join("scraped_sites", "ambitionbox_dataset")
DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def parse_count(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    match = re.search(r"([\d.]+)\s*([kKlL]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "k":
        number *= 1_000
    elif suffix == "l":
        number *= 100_000
    return int(number)


def names_from_list(value):
    if not isinstance(value, list):
        return ""
    return ", ".join(item.get("name", "") for item in value if isinstance(item, dict) and item.get("name"))


def city_state(value):
    if isinstance(value, dict):
        return value.get("cityState") or value.get("name") or ""
    return value or ""


def request_html(session, url, delay):
    if delay:
        time.sleep(delay + random.uniform(0, delay / 2))
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def extract_listing_companies(html):
    soup = BeautifulSoup(html, "html.parser")
    companies = []

    for card in soup.select(".companyCardWrapper"):
        text = card.get_text(" ", strip=True)
        review_link = card.find("a", href=re.compile(r"/reviews/[^/]+-reviews"))
        if not review_link:
            continue

        review_url = urljoin(BASE_URL, review_link["href"])
        slug = review_url.rstrip("/").split("/")[-1].removesuffix("-reviews")
        overview_url = f"{BASE_URL}/overview/{slug}-overview"

        title_match = re.match(r"(.+?)\s+Follow\s+([\d.]+)\s+\(([^)]+)\)\s+(.+?)\s+\|\s+(.+?)(?:\s+\+\d+ other locations|\s+Highly Rated|\s+Critically Rated|\s+To view salary|$)", text)
        name = title_match.group(1).strip() if title_match else ""
        rating = float(title_match.group(2)) if title_match else None
        rating_count = parse_count(title_match.group(3)) if title_match else None
        industry = title_match.group(4).strip() if title_match else ""
        primary_location = title_match.group(5).strip() if title_match else ""

        metrics = {}
        for label in ["Reviews", "Salaries", "Interviews", "Jobs", "Benefits", "Photos"]:
            match = re.search(rf"([\d.]+\s*[kKlL]?|\d+)\s+{label}", text)
            metrics[f"{label.lower()}_count"] = parse_count(match.group(1)) if match else None

        companies.append({
            "company_name": name,
            "url_name": slug,
            "overview_url": overview_url,
            "review_url": review_url,
            "listing_rating": rating,
            "listing_rating_count": rating_count,
            "listing_industry": industry,
            "listing_primary_location": primary_location,
            **metrics,
        })

    return companies


def extract_overview_data(html, fallback):
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return fallback

    props = json.loads(script.string).get("props", {}).get("pageProps", {})
    meta = props.get("companyMetaInformation", {})
    header = props.get("companyHeaderData", {})
    stats = {
        f"{item.get('name', '').lower()}_count": item.get("count")
        for item in props.get("companyStatsData", [])
        if isinstance(item, dict) and item.get("count") is not None
    }
    office_locations = props.get("officeLocations") or []

    return {
        **fallback,
        "company_name": meta.get("companyName") or header.get("companyName") or fallback.get("company_name"),
        "short_name": meta.get("shortName") or header.get("companyName") or fallback.get("company_name"),
        "rating": round(float(meta.get("rating") or header.get("rating") or fallback.get("listing_rating") or 0), 2),
        "followers_count": meta.get("followersCount") or header.get("followersCount"),
        "indian_employee_count": meta.get("indianEmployeeCount"),
        "indian_employee_count_range": meta.get("indianEmployeeCountRange"),
        "global_employee_count_range": meta.get("globalEmployeeCount"),
        "employee_presence": meta.get("employeePresence"),
        "industry": meta.get("primaryIndustryName") or fallback.get("listing_industry"),
        "founded_year": meta.get("foundedYear"),
        "hq": city_state(meta.get("hq")),
        "india_hq": city_state(meta.get("indiaHQ")),
        "ceo": meta.get("ceo"),
        "company_type": names_from_list(meta.get("typeOfCompany")),
        "business_nature": names_from_list(meta.get("natureOfBusiness")),
        "ownership": (meta.get("ownership") or {}).get("name") if isinstance(meta.get("ownership"), dict) else "",
        "website": meta.get("website"),
        "office_locations_count": len(office_locations),
        "top_office_locations": ", ".join(loc.get("name", "") for loc in office_locations[:5] if isinstance(loc, dict)),
        "reviews_count": stats.get("reviews_count") or fallback.get("reviews_count"),
        "salaries_count": stats.get("salaries_count") or fallback.get("salaries_count"),
        "interviews_count": stats.get("interviews_count") or fallback.get("interviews_count"),
        "jobs_count": stats.get("jobs_count") or fallback.get("jobs_count"),
        "benefits_count": stats.get("benefits_count") or fallback.get("benefits_count"),
        "photos_count": stats.get("photos_count") or fallback.get("photos_count"),
    }


def scrape_ambitionbox_dataset(pages, limit, delay):
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(DEFAULT_USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    })

    listing_companies = []
    for page in range(1, pages + 1):
        url = f"{BASE_URL}/list-of-companies" if page == 1 else f"{BASE_URL}/list-of-companies?page={page}"
        print(f"Fetching listing page {page}: {url}")
        html = request_html(session, url, delay)
        listing_companies.extend(extract_listing_companies(html))
        if limit and len(listing_companies) >= limit:
            listing_companies = listing_companies[:limit]
            break

    dataset = []
    for index, company in enumerate(listing_companies, start=1):
        print(f"[{index}/{len(listing_companies)}] Fetching {company['company_name'] or company['url_name']}")
        try:
            html = request_html(session, company["overview_url"], delay)
            dataset.append(extract_overview_data(html, company))
        except Exception as exc:
            company["error"] = str(exc)
            dataset.append(company)

    return dataset


def write_outputs(dataset):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(OUTPUT_DIR, f"ambitionbox_companies_{timestamp}.json")
    csv_path = os.path.join(OUTPUT_DIR, f"ambitionbox_companies_{timestamp}.csv")

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(dataset, file, indent=2, ensure_ascii=False)

    fieldnames = sorted({key for row in dataset for key in row.keys()})
    with open(csv_path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(dataset)

    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description="Extract AmbitionBox company data for modelling datasets.")
    parser.add_argument("--pages", type=int, default=1, help="Listing pages to scrape, 20 companies per page.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum companies to enrich.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds.")
    args = parser.parse_args()

    dataset = scrape_ambitionbox_dataset(args.pages, args.limit, args.delay)
    json_path, csv_path = write_outputs(dataset)
    print(f"\nSaved {len(dataset)} companies")
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")


if __name__ == "__main__":
    main()
