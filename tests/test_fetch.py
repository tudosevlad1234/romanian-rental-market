import pytest
import requests

from rentals.fetch import FetchError, PoliteFetcher, RobotsDenied, SeleniumFetcher


class Response:
    def __init__(self, status=200, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


class Session:
    def __init__(self, routes):
        self.routes, self.headers, self.calls = routes, {}, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        result = self.routes.get(url, Response(404))
        if isinstance(result, list):
            result = result.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make(routes, **options):
    sleeps = []
    clock = {"now": 0.0}

    def sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    fetcher = PoliteFetcher(session=Session(routes), sleep=sleep, clock=lambda: clock["now"], **options)
    return fetcher, sleeps


def test_sets_identifying_user_agent():
    fetcher, _ = make({}, user_agent="thesis-bot (me@uni.ro)")
    assert fetcher.session.headers["User-Agent"] == "thesis-bot (me@uni.ro)"


def test_robots_disallow_blocks_request():
    routes = {
        "https://a.ro/robots.txt": Response(200, "User-agent: *\nDisallow: /private/"),
        "https://a.ro/public/1": Response(200, "ok"),
        "https://a.ro/private/1": Response(200, "secret"),
    }
    fetcher, _ = make(routes, delay=0)
    assert fetcher.get("https://a.ro/public/1") == "ok"
    with pytest.raises(RobotsDenied):
        fetcher.get("https://a.ro/private/1")
    assert "https://a.ro/private/1" not in fetcher.session.calls
    assert fetcher.session.calls.count("https://a.ro/robots.txt") == 1


def test_robots_forbidden_means_no_access_and_missing_means_allowed():
    forbidden, _ = make({"https://a.ro/robots.txt": Response(403)}, delay=0)
    with pytest.raises(RobotsDenied):
        forbidden.get("https://a.ro/x")
    missing, _ = make({"https://a.ro/x": Response(200, "ok")}, delay=0)
    assert missing.get("https://a.ro/x") == "ok"


def test_unreachable_robots_means_no_access():
    server_error, _ = make({"https://a.ro/robots.txt": Response(503), "https://a.ro/x": Response(200, "ok")}, delay=0)
    with pytest.raises(RobotsDenied):
        server_error.get("https://a.ro/x")
    down, _ = make({"https://a.ro/robots.txt": requests.ConnectionError("down")}, delay=0)
    with pytest.raises(RobotsDenied):
        down.get("https://a.ro/x")


def test_robots_can_be_switched_off_for_local_use():
    fetcher, _ = make({"https://a.ro/x": Response(200, "ok")}, delay=0, respect_robots=False)
    assert fetcher.get("https://a.ro/x") == "ok"
    assert fetcher.session.calls == ["https://a.ro/x"]


def test_throttle_spaces_requests_per_host():
    routes = {f"https://a.ro/{i}": Response(200, "ok") for i in range(3)}
    routes["https://b.ro/1"] = Response(200, "ok")
    fetcher, sleeps = make(routes, delay=2.5, respect_robots=False)
    for url in ("https://a.ro/0", "https://a.ro/1", "https://a.ro/2"):
        fetcher.get(url)
    assert sleeps == [2.5, 2.5]
    fetcher.get("https://b.ro/1")
    assert sleeps == [2.5, 2.5]


def test_retries_transient_status_with_backoff_and_retry_after():
    routes = {"https://a.ro/x": [Response(503), Response(429, headers={"Retry-After": "40"}), Response(200, "ok")]}
    fetcher, sleeps = make(routes, delay=0, respect_robots=False, backoff=(10.0, 30.0, 90.0))
    assert fetcher.get("https://a.ro/x") == "ok"
    assert [s for s in sleeps if s > 0] == [10.0, 40.0]


def test_gives_up_after_backoffs_exhausted():
    fetcher, _ = make({"https://a.ro/x": [Response(500)] * 4}, delay=0, respect_robots=False, backoff=(1.0, 1.0))
    with pytest.raises(FetchError, match="HTTP 500"):
        fetcher.get("https://a.ro/x")


def test_404_is_not_retried():
    fetcher, _ = make({"https://a.ro/x": Response(404)}, delay=0, respect_robots=False)
    with pytest.raises(FetchError, match="404"):
        fetcher.get("https://a.ro/x")
    assert fetcher.session.calls == ["https://a.ro/x"]


def test_connection_errors_retry_then_raise():
    boom = requests.ConnectionError("reset")
    fetcher, _ = make({"https://a.ro/x": [boom, Response(200, "ok")]}, delay=0, respect_robots=False)
    assert fetcher.get("https://a.ro/x") == "ok"
    failing, _ = make({"https://a.ro/y": [boom] * 5}, delay=0, respect_robots=False, backoff=(1.0,))
    with pytest.raises(FetchError):
        failing.get("https://a.ro/y")


class Driver:
    def __init__(self):
        self.visited, self.page_source, self.quit_called = [], "<html>rendered</html>", False

    def get(self, url):
        self.visited.append(url)

    def quit(self):
        self.quit_called = True


def test_selenium_fetcher_respects_robots_and_returns_rendered_source():
    robots = PoliteFetcher(
        session=Session({"https://a.ro/robots.txt": Response(200, "User-agent: *\nDisallow: /no")}),
        sleep=lambda s: None,
    )
    driver = Driver()
    fetcher = SeleniumFetcher(driver=driver, delay=0, robots_fetcher=robots, sleep=lambda s: None)
    assert fetcher.get("https://a.ro/yes") == "<html>rendered</html>"
    with pytest.raises(RobotsDenied):
        fetcher.get("https://a.ro/no")
    assert driver.visited == ["https://a.ro/yes"]
    fetcher.close()
    assert driver.quit_called


def test_selenium_missing_gives_clear_message(monkeypatch):
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("selenium"):
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ImportError, match="optional extra"):
        SeleniumFetcher.start_driver("agent")
