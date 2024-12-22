from pathlib import Path
from loguru import logger
from src.utils import request_serp
from utils import load_config, get_dblp_items, request_dblp, init_serp_params
import yaml


class PaperWatcher:
    def __init__(self, mode='dev', config_path="config.yaml"):
        self.config = load_config(config_path)
        self.mode = mode
        self.query_depth = 3 if mode == "dev" else -1
        self.readme_path = self.config["readme_path"]
        self.channel = self.config["channel"]
        self.cache_path = Path(f"{self.config['cache_path']}/{self.channel}.yaml")
        self.cached_data = self.load_cached_data()
        self.new_data = {}

        logger.info(f"running with {self.mode} mode")

    def load_cached_data(self):
        cached_data = yaml.safe_load(open(self.cache_path, "r")) if self.cache_path.exists() else {}
        if cached_data is None:
            cached_data = {}
        return cached_data

    def run(self):
        msg = self.update_cached_data()
        self.update_readme()
        if self.mode == "prod" and msg != '':
            import os
            env_file = os.getenv("GITHUB_ENV")
            with open(env_file, "a") as f:
                f.write(f"MSG=$'{msg}'")

    def generate_message(self):
        table_lines=[]
        for topic in self.new_data.keys():
            items = self.new_data[topic]
            total = len(items)
            if total > 0:
                table_lines.append(f"## Explore {total} new papers about {topic}\\n")
                table_lines = ["| Index | Year | Title | Venue |",
                               "|-------|------|-------|-------|"]
                # Github issue allow max 65535 characters, so we show the first 10 items for one topic
                items_showing = min(10, total)
                for idx, item in enumerate(items[:items_showing]):
                    table_lines.append(f"| [{idx}]({item['url']}) | {item['year']} | {item['title']} | {item['venue']}")
                if total > items_showing:
                    table_lines.append(f"| ... | ... | ... | ... |")
        return "\\n".join(table_lines)


    def update_cached_data(self):
        cached_data = self.load_cached_data()
        topics = self.config[self.channel]["topics"]
        logger.info(f"topics: {topics}")
        for topic in topics:
            if self.channel == "dblp":
                received_data = request_dblp(topic)
                if received_data is None:
                    logger.error(f"dblp data is None, topic: {topic}")
                    continue
                items = get_dblp_items(received_data)
            else:
                params = init_serp_params(topic)
                items = request_serp(params=params, depth=self.query_depth)

            topic_cached_items = cached_data.get(topic, [])
            topic_new_items = [item for item in items if item not in topic_cached_items]
            logger.info(f"total {len(topic_new_items)} new items about topic {topic}")

            if topic not in cached_data:
                cached_data[topic] = []
            cached_data[topic].extend(topic_new_items)

            if len(topic_new_items) > 0:
                self.new_data[topic] = topic_new_items

        msg = self.generate_message()
        yaml.safe_dump(cached_data, open(self.cache_path, "w"), sort_keys=False, indent=2)

        return msg


    def update_readme(self):
        papers = self.cached_data
        papers_list = list(papers.values())
        papers_list = sum(papers_list, [])

        papers_list.sort(key=lambda x: x['year'], reverse=True)

        total = len(papers_list)
        if self.channel == "dblp":
            table_lines = ["| Index | Year | type | Title | Authors | Venue | DOI |",
                           "|-------|------|------|-------|---------|-------|-----|"]
            for idx, paper in enumerate(papers_list):
                authors = paper['author']
                table_line = f"| [{total-idx}]({paper['ee']}) | {paper['year']} | {paper['type']} | {paper['title']} | {authors} | {paper['venue']} | {paper['doi']} |"
                table_lines.append(table_line)
        else:
            table_lines = ["| Index | Year | Title | Venue | CitedBy |",
                           "|-------|------|-------|-------|---------|"]
            for idx, paper in enumerate(papers_list):
                table_line = f"| [{total-idx}]({paper['url']}) | {paper['year']} | {paper['title']} | {paper['venue']} | {paper['cited_by']} |"
                table_lines.append(table_line)

        markdown_table = "\n".join(table_lines)

        with open(self.readme_path, 'r') as file:
            lines = file.readlines()

        new_lines = []
        for line in lines:
            if line.startswith("## All Papers"):
                new_lines.append(line)
                new_lines.append("\n")
                new_lines.append(markdown_table)
                new_lines.append("\n\n")
                break
            else:
                new_lines.append(line)

        with open(self.readme_path, 'w') as file:
            file.writelines(new_lines)


if __name__ == "__main__":
    dblp = PaperWatcher(mode='dev')
    dblp.update_readme()