"""Run currency updates as one separate, long-lived process."""
import logging
import threading

from backend.database import initialize_database
from backend.common.live_rates import refresh_if_due


def main():
    logging.basicConfig(level=logging.INFO)
    initialize_database()
    while True:
        try:
            refresh_if_due()
        except Exception:
            logging.exception('Currency rate scheduler failed')
        threading.Event().wait(60)


if __name__ == '__main__':
    main()
