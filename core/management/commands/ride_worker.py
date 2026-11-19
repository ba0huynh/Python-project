"""
Dispatcher worker: run ONE of these next to the web server(s) when REDIS_URL is
set. Without Redis the web process runs the dispatcher itself
(RIDE_WORKER_EMBEDDED, see core/consumers.py) and this command isn't needed.

    python manage.py ride_worker            # loop forever (production / dev)
    python manage.py ride_worker --once     # single pass (cron / tests)

Each pass: cancels searches older than RIDE_SEARCH_SECONDS, times out
unanswered offers and offers waiting rides to the next nearest drivers
(including drivers who just came online).
"""
import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.services import run_dispatch_cycle

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the ride dispatcher loop (offers, timeouts).'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=float, default=2.0, help='Seconds between passes')
        parser.add_argument('--once', action='store_true', help='Run a single pass and exit')

    def handle(self, *args, interval, once, **options):
        if once:
            run_dispatch_cycle()
            return
        stop = {'flag': False}

        def request_stop(*_):
            stop['flag'] = True

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        self.stdout.write(f'Ride worker started (every {interval}s). Ctrl+C to stop.')
        while not stop['flag']:
            close_old_connections()
            try:
                run_dispatch_cycle()
            except Exception:  # keep the loop alive; the next pass retries
                logger.exception('Dispatch cycle failed')
            time.sleep(interval)
        self.stdout.write('Ride worker stopped.')
