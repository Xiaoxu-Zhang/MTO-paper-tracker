import ezkfg as ez
import json
import os
import random
import requests
import sys
import time
import yaml

from loguru import logger
from pathlib import Path
from serpapi import GoogleSearch

def init_log():
    """Initialize loguru log information"""
    event_logger_format = (
        "<g>{time:YYYY-MM-DD HH:mm:ss}</g> | "
        "<lvl>{level}</lvl> - "
        # "<c><u>{name}</u></c> | "
        "{message}"
    )
    logger.remove()
    logger.add(
        sink=sys.stdout,
        colorize=True,
        level="DEBUG",
        format=event_logger_format,
        diagnose=False,
    )

    return logger


def request_serp(params, depth=-1):
    all_items = []
    curr_depth = 0
    while params is not None:
        data = request_serp_data(params)
        if data is not None:
            all_items += refine_serp_items(data)
            serpapi_pagination = data.get("serpapi_pagination", {})
            next_url = serpapi_pagination.get("next", None)
            params = init_serp_params(next_url) if next_url else None
            curr_depth += 1
        else:
            logger.error(f"data is None")
            params = None
        if curr_depth > depth > 0:
            return all_items
    return all_items


def request_serp_data(params):
    try:
        search = GoogleSearch(params)
    except Exception as e:
        logger.error(f"Exception: {e}")
        return None
    results = search.get_json()
    status = results["search_metadata"]["status"]
    total = results["search_information"]["total_results"]
    try:
        prev_total = yaml.safe_load(open("cached/total.yaml", "r"))
    except FileNotFoundError:
        prev_total = {"google_scholar": 0}
    if total == prev_total.get("google_scholar"):
        total_yaml = {"google_scholar": total}
        try:
            yaml.dump(total_yaml, open("cached/total.yaml", "w"))
        except Exception as e:
            logger.error(f"Failed to save total.yaml, {e}")
        return None
    if status == "Success":
        return results
    else:
        logger.error(f"SerpAPI request failed")


def init_serp_params(target_url):
    from urllib.parse import urlparse, parse_qs
    api_key = os.getenv("SERP_API_KEY")
    if not api_key:
        print("SerpAPI API Key not found in environment variables.")
        return
    if "https" in target_url:
        parsed_url = urlparse(target_url)
        query_params = parse_qs(parsed_url.query)
        search_parameters = {
            "engine": query_params.get("engine", [""])[0],
            "q": query_params.get("q", [""])[0],
            "hl": query_params.get("hl", [""])[0],
            "start": int(query_params.get("start", [0])[0]),
            "as_sdt": query_params.get("as_sdt", [""])[0],
            "api_key": api_key
        }
    else:
        search_parameters = {
            "engine": "google_scholar",
            "q": target_url,
            "hl": "en",
            "start": 0,
            "as_sdt": "0,11",
            "api_key": api_key
        }
    return search_parameters


def refine_serp_items(json_data=None):
    if json_data is None:
        with open('cached/serp_res.json', 'r', encoding='utf-8') as file:
            json_data = json.load(file)
        data = json_data.get("organic_results", [])
    else:
        data = json_data.get("organic_results", [])
    papers = []
    for entry in data:
        summary = entry["publication_info"]["summary"]
        summary = summary.split(" - ")
        try:
            authors, venue, _ = summary
        except ValueError as e:
            logger.info(f"summary is {summary}, {e}")
            authors, venue= ["Unknown", "Unknown"]
        try:
            venue, year = venue.split(",")
        except ValueError as e:
            logger.info(f"venue is {venue}, {e}")
            venue, year = ["-", "-"]
        paper_info = {
            "title": entry.get("title", ""),
            "authors": authors.strip(),
            "url": entry.get("link", ""),
            "cited_by": entry["inline_links"]["cited_by"]["total"],
            "venue": venue,
            "year": year.strip(),
        }
        papers.append(paper_info)

    return papers


def load_config(cfg_path: str):
    cfg = ez.Config().load(cfg_path)
    cfg["cache_path"] = Path(cfg["cache_path"])
    cfg["cache_path"].mkdir(parents=True, exist_ok=True)
    init_log()
    return cfg


def get_item_info(item, key):
    try:
        return item[key]
    except KeyError:
        return ""


def get_dblp_items(dblp_data):
    try:
        items = dblp_data["result"]["hits"]["hit"]
    except KeyError:
        items = []

    # item{'author', 'title', 'venue', 'year', 'type', 'access', 'key', 'doi', 'ee', 'url'}
    res_items = []

    for item in items:
        res_item = {}
        # format author
        authors = get_item_info(item["info"], "authors")
        try:
            authors = [author["text"] for author in authors["author"]]
        except TypeError:
            if "author" not in authors:
                continue
            if "text" not in authors["author"]:
                continue

            authors = [authors["author"]["text"]]

        # logger.info(f"authors: {authors}")

        res_item["author"] = ", ".join(authors)
        needed_keys = [
            "title",
            "venue",
            "year",
            "type",
            "access",
            "key",
            "doi",
            "ee",
            "url",
        ]
        for key in needed_keys:
            key_temp = get_item_info(item["info"], key)
            res_item[key] = key_temp if key_temp else ""

        res_items.append(res_item)

    return res_items


def request_dblp(topic, retry=10, sleep_time=5):
    api_url = "https://dblp.org/search/publ/api?q={}&format=json&h=1000"
    url = api_url.format(topic)
    try:
        time.sleep(sleep_time + random.random() * 3)
        response = requests.get(url)
        response.raise_for_status()  # 如果响应状态不是200，将引发HTTPError异常
        data = response.json()
    # deal with errors
    except Exception as e:
        logger.error(f"Exception: {e}")
        if retry > 0:
            logger.info(f"retrying {url}")
            return request_dblp(url, retry - 1)
        else:
            logger.error(f"Failed to request {url}")
        return None
    else:
        return data