import os

# Opt in to python-telegram-bot's future timedelta API (as the app does in __main__),
# which also silences its deprecation warning.
os.environ.setdefault("PTB_TIMEDELTA", "1")
