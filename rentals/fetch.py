from __future__ import annotations

import logging
import time
from urllib import robotparser
from urllib.parse import urlsplit

import requests

log = logging.getLogger("rentals.fetch")

DEFAULT_USER_AGENT = "rental-market-research/1.0 (academic research; contact: set-your-email@example.com)"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class FetchError(Exception):
    pass


class RobotsDenied(FetchError):
    pass


class PoliteFetcher:
    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        delay: float = 2.5,
        backoff: tuple[float, ...] = (10.0, 30.0, 90.0),
        respect_robots: bool = True,
        timeout: float = 20.0,
        session=None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.user_agent = user_agent
        self.delay = delay
        self.backoff = backoff
        self.respect_robots = respect_robots
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.5"})
        self.sleep = sleep
        self.clock = clock
        self.last_request: dict[str, float] = {}
        self.robots: dict[str, robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self.robots:
            self.robots[host] = self.load_robots(host)
        parser = self.robots[host]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def load_robots(self, host: str):
        parser = robotparser.RobotFileParser()
        try:
            response = self.session.get(f"{host}/robots.txt", timeout=self.timeout)
        except requests.RequestException as error:
            log.warning("robots.txt for %s unreachable (%s); treating the site as off limits", host, error)
            parser.parse(["User-agent: *", "Disallow: /"])
            return parser
        if response.status_code in (401, 403) or response.status_code >= 500:
            parser.parse(["User-agent: *", "Disallow: /"])
            return parser
        if response.status_code >= 400:
            return None
        parser.parse(response.text.splitlines())
        return parser

    def throttle(self, host: str) -> None:
        elapsed = self.clock() - self.last_request.get(host, -1e9)
        if elapsed < self.delay:
            self.sleep(self.delay - elapsed)
        self.last_request[host] = self.clock()

    def get(self, url: str) -> str:
        if not self.allowed(url):
            raise RobotsDenied(f"robots.txt disallows {url}")
        host = urlsplit(url).netloc
        attempt = 0
        while True:
            self.throttle(host)
            try:
                response = self.session.get(url, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as error:
                if attempt >= len(self.backoff):
                    raise FetchError(f"{url}: {error}") from error
                self.sleep(self.backoff[attempt])
                attempt += 1
                continue
            if response.status_code in RETRY_STATUS and attempt < len(self.backoff):
                retry_after = response.headers.get("Retry-After", "")
                pause = self.backoff[attempt]
                if retry_after.replace(".", "", 1).isdigit():
                    pause = max(pause, float(retry_after))
                log.warning("HTTP %s on %s, retrying in %ss", response.status_code, url, pause)
                self.sleep(pause)
                attempt += 1
                continue
            if response.status_code >= 400:
                raise FetchError(f"{url}: HTTP {response.status_code}")
            return response.text


class SeleniumFetcher:
    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        delay: float = 2.5,
        wait_seconds: float = 10.0,
        wait_for: str | None = None,
        driver=None,
        respect_robots: bool = True,
        robots_fetcher: PoliteFetcher | None = None,
        sleep=time.sleep,
    ):
        self.user_agent = user_agent
        self.delay = delay
        self.wait_seconds = wait_seconds
        self.wait_for = wait_for
        self.sleep = sleep
        self.driver = driver or self.start_driver(user_agent)
        self.robots = robots_fetcher or PoliteFetcher(user_agent=user_agent, respect_robots=respect_robots)

    @staticmethod
    def start_driver(user_agent: str):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as error:
            raise ImportError("install the optional extra: pip install '.[selenium]'") from error
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument(f"--user-agent={user_agent}")
        return webdriver.Chrome(options=options)

    def get(self, url: str) -> str:
        if not self.robots.allowed(url):
            raise RobotsDenied(f"robots.txt disallows {url}")
        self.sleep(self.delay)
        try:
            self.driver.get(url)
            if self.wait_for:
                self.wait_until_present()
            return self.driver.page_source
        except Exception as error:
            raise FetchError(f"{url}: {error}") from error

    def wait_until_present(self) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as conditions
        from selenium.webdriver.support.ui import WebDriverWait

        WebDriverWait(self.driver, self.wait_seconds).until(
            conditions.presence_of_element_located((By.CSS_SELECTOR, self.wait_for))
        )

    def close(self) -> None:
        self.driver.quit()
