import time
import threading
import functools
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager


class AutoQuitDriverManager:
    def __init__(self, headless=True, idle_timeout=300, check_interval=5):
        """
        headless: run Chrome headless
        idle_timeout: seconds of inactivity before auto-quit
        check_interval: how often to check idle time (seconds)
        """
        self.headless = headless
        self.idle_timeout = idle_timeout
        self.check_interval = check_interval
        self.driver = None
        self.last_used = None
        self.lock = threading.Lock()
        self._init_driver()
        self._start_watcher()

    def _init_driver(self):
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--log-level=3")
        options.add_experimental_option(
            "excludeSwitches",
            ["enable-logging"]
        ) # suppress DevTools/GCM logs

        if self.driver:
            self.quit()

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        self.last_used = time.time()

    def get_driver(self) -> webdriver.Chrome:
        with self.lock:
            if self.driver is None:
                self._init_driver()
            self.last_used = time.time()
            return self.driver

    def quit(self):
        with self.lock:
            if self.driver:
                self.driver.quit()
                self.driver = None
                self.last_used = None

    def _watcher(self):
        while True:
            time.sleep(self.check_interval)
            with self.lock:
                if self.driver and self.last_used:
                    idle_time = time.time() - self.last_used
                    if idle_time > self.idle_timeout:
                        print(f"Driver idle for {idle_time:.1f}s → quitting")
                        self.quit()

    def _start_watcher(self):
        thread = threading.Thread(target=self._watcher, daemon=True)
        thread.start()


def cache_driver(driver_manager_accessor):
    cached_driver_manager = {}
    @functools.wraps(driver_manager_accessor)
    def wrapper(*args, **kwargs):
        cache_key = (driver_manager_accessor.__name__, args, frozenset(kwargs.items()))
        if driver_manager := cached_driver_manager.get(cache_key):
            return driver_manager
        cached_driver_manager[cache_key] = driver_manager_accessor(*args, **kwargs)
        return cached_driver_manager[cache_key]
    return wrapper


@cache_driver
def access_chrome_driver_manager(headless=True,
                        idle_timeout=300,
                        check_interval=5) -> AutoQuitDriverManager:

    return AutoQuitDriverManager(
        headless=headless,
        idle_timeout=idle_timeout,
        check_interval=check_interval
    )
