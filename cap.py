from lifesaver.logging import setup_logging
from bottlecap import BottlecapBot

setup_logging()
BottlecapBot.with_config().run()
