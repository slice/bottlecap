from lifesaver.bot import Bot


class BottlecapBot(Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_all()
