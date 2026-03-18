import schedule
import time
import threading
import logging
from src.config_parser import load_configurations, get_config_value

logger = logging.getLogger(__name__)

class Scheduler:
    def __init__(self, interval):
        self.interval = interval
        self._jobs = []
        self._running = False
        self._thread = None

    def job(self, func):
        self._jobs.append(func)
        return func

    def _run_jobs(self):
        while self._running:
            schedule.run_pending()
            time.sleep(1)

    def start(self):
        if self._running:
            logger.warning("Scheduler is already running.")
            return
        self._running = True
        for job_func in self._jobs:
            # Schedule all jobs with the same interval for now
            # In a more complex scenario, each job might have its own interval
            if self.interval < 60:
                schedule.every(self.interval).seconds.do(job_func)
                logger.info(f"Scheduled job {job_func.__name__} every {self.interval} seconds.")
            else:
                schedule.every(self.interval // 60).minutes.do(job_func)
                logger.info(f"Scheduled job {job_func.__name__} every {self.interval // 60} minutes.")

        self._thread = threading.Thread(target=self._run_jobs)
        self._thread.daemon = True
        self._thread.start()
        logger.info("Scheduler started.")

    def stop(self):
        if not self._running:
            logger.warning("Scheduler is not running.")
            return
        self._running = False
        if self._thread:
            self._thread.join() # Wait for the thread to finish
        logger.info("Scheduler stopped.")







