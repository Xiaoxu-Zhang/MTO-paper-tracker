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

def load_previous_total():
    try:
        prev_total = yaml.safe_load(open("cached/total.yaml", "r"))
        prev_total = prev_total.get("google_scholar", 0)
    except FileNotFoundError:
        prev_total = 0
    return prev_total

def update_total(total):
    total_yaml = {"google_scholar": total}
    try:
        yaml.safe_dump(total_yaml, open("cached/total.yaml", "w"))
    except Exception as e:
        logger.error(f"Failed to save total.yaml, {e}")

def request_serp(params, depth=-1, api_key_name="SERP_API_KEY"):
    all_items = []
    curr_depth = depth
    prev_total = load_previous_total()
    curr_total = None
    while params is not None:
        if curr_depth <= 0:
            logger.info(f"Reached max depth.")
            break
        res = request_serp_data(params, prev_total)
        if res is None:
            data = None
        elif "error" in res:
            return ["error"]
        else:
            data, curr_total = res
        if data is not None:
            all_items += refine_serp_items(data)
            serpapi_pagination = data.get("serpapi_pagination", {})
            next_url = serpapi_pagination.get("next", None)
            params = init_serp_params(next_url, api_key_name)
            curr_depth -= 1
        else:
            logger.info(f"serp data is None")
            params = None
    if curr_total:
        update_total(curr_total)
    return all_items


def request_serp_data(params, prev_total):
    try:
        search = GoogleSearch(params)
        results = search.get_json()
    except Exception as e:
        logger.error(f"Request SerpAPI failed with exception: {e}")
        return
    if len(results) == 1 and "error" in results:
        logger.error(f"SerpApi:{results['error']}")
        return results

    status = results.get("search_metadata", {}).get("status", {})
    if status == "Success":
        curr_total = results.get("search_information", {}).get("total_results", 0)
        if curr_total > prev_total:
            return results, curr_total
        else:
            logger.info(f"Current total({curr_total}) is no more than previous({prev_total})")
    else:
        logger.error(f"SerpAPI request was not success, result was {results}")


def init_serp_params(target_url, api_key_name):
    if target_url is None:
        return
    from urllib.parse import urlparse, parse_qs
    api_key = os.getenv(api_key_name)
    if not api_key:
        logger.error("SerpAPI API Key not found in environment variables.")
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
        return []
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
        cited_by = entry.get("inline_links", {})
        cited_by = cited_by.get("cited_by", {})
        cited_by = cited_by.get("total", 0)
        paper_info = {
            "title": entry.get("title", ""),
            "authors": authors.strip(),
            "url": entry.get("link", ""),
            "cited_by": cited_by,
            "venue": venue,
            "year": year.strip(),
        }
        papers.append(paper_info)

    return papers


def load_config(cfg_path: str):
    cfg = yaml.safe_load(open(cfg_path, "r"))
    path = Path(cfg["cache_path"])
    path.mkdir(parents=True, exist_ok=True)
    init_log()
    return cfg

def save_config(file_path: str, cfg_data:dict):
    _path = Path(file_path)
    with _path.open('w') as f:
        yaml.safe_dump(cfg_data, f, sort_keys=False, indent=2)


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