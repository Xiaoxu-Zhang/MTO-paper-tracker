from pathlib import Path
from loguru import logger
from src.utils import request_serp
from utils import load_config, save_config, get_dblp_items, request_dblp, init_serp_params
import yaml


class PaperWatcher:
    def __init__(self, mode='dev', config_path="config.yaml"):
        self.config = load_config(config_path)
        self.config_path = config_path
        self.mode = mode
        self.readme_path = self.config["readme_path"]
        self.channel = self.config["channel"]

        channel_cfg = self.config.get(self.channel, {})
        if mode == "dev":
            self.query_depth = 2
        else:
            self.query_depth = channel_cfg.get("query_depth", 2)

        self.cache_path = Path(f"{self.config['cache_path']}/{self.channel}.yaml")
        self.cached_data = self.load_cached_data()
        self.new_data = {}

        logger.info(f"running with {self.mode} mode")

    def load_cached_data(self):
        cached_data = yaml.safe_load(open(self.cache_path, "r")) if self.cache_path.exists() else {}
        if cached_data is None:
            cached_data = {}
        return cached_data

    @staticmethod
    def preview_message(msg):
        with open("mail.md", "w") as f:
            f.write(msg)

    def run(self):
        msg = self.update_cached_data()
        self.update_readme()
        if msg != '':
            if self.mode == "dev":
                self.preview_message(msg)
            if self.mode == "prod":
                import os
                env_file = os.getenv("GITHUB_ENV")
                with open(env_file, "a") as f:
                    f.write(f"MSG<<EOF\n{msg}\nEOF")

    def generate_message(self):
        markdown_lines=[]
        for topic in self.new_data.keys():
            items = self.new_data[topic]
            total = len(items)
            if total > 0:
                markdown_lines.append(f"## Explore {total} new papers about {topic.replace('%20', ' ')}\n")
                markdown_lines.append("Click [year] to jump to paper page.")
                # Github issue allow max 65535 characters, so we show the first 10 items for one topic
                items_showing = min(10, total)
                for idx, item in enumerate(items[:items_showing]):
                    link_key = 'url' if self.channel == 'serp' else 'ee'
                    _index = idx+1
                    year = item['year']
                    link = item[link_key]
                    title = item['title']
                    venue = item['venue']
                    markdown_lines.append(f"{_index}. [[{year}]({link})] {title} --on-- {venue}")
                if total > items_showing:
                    markdown_lines.append(f"...")
                if self.channel == "serp":
                    markdown_lines.append("\n See original [web page](https://scholar.google.com/scholar?hl=en&as_sdt=0%2C5&q=allintitle%3A+optimization+%22many-task%22+OR+%22multitask%22+OR+%22multitasking%22+OR+%22multi-task%22+-learning&btnG=) for more info")
        msg = "\n".join(markdown_lines)
        return msg


    def update_cached_data(self):
        topics = self.config[self.channel]["topics"]
        logger.info(f"topics: {topics}")
        total_topic = len(topics)
        topic_id = 0
        total_try = 1
        while topic_id < total_topic:
            topic = topics[topic_id]
            if self.channel == "dblp":
                received_data = request_dblp(topic)
                if received_data is None:
                    logger.error(f"dblp data is None, topic: {topic}")
                    topic_id += 1
                    continue
                items = get_dblp_items(received_data)
            else:
                api_key_total = self.config[self.channel]["api_key_total"]
                api_key_current_id = self.config[self.channel]["api_key_current_id"]
                api_key_name = self.config[self.channel]["api_key_names"][api_key_current_id]
                logger.info(f"api_key_name: {api_key_name}")
                params = init_serp_params(topic, api_key_name)
                items = request_serp(params=params, depth=self.query_depth, api_key_name=api_key_name)
                if items == ["error"]:
                    api_key_current_id = (api_key_current_id + 1) % api_key_total
                    self.config[self.channel]["api_key_current_id"] = api_key_current_id
                    total_try += 1
                    if total_try > api_key_total:
                        logger.error(f"All api keys are used up, please add more api keys")
                        break
                    continue
            topic_id += 1
            topic_cached_items = self.cached_data.get(topic, [])
            topic_new_items = [item for item in items if item not in topic_cached_items]
            logger.info(f"total {len(topic_new_items)} new items about topic {topic}")

            if topic not in self.cached_data:
                self.cached_data[topic] = []
            self.cached_data[topic].extend(topic_new_items)

            if len(topic_new_items) > 0:
                self.new_data[topic] = topic_new_items

        msg = self.generate_message()
        yaml.safe_dump(self.cached_data, open(self.cache_path, "w"), sort_keys=False, indent=2)
        yaml.safe_dump(self.config, open(self.config_path, "w"), sort_keys=False, indent=2)

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