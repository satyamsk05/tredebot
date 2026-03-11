import json
import os
import logging

BET_SEQUENCE = [3, 6, 18, 35, 73, 150, 310]

class Martingale:
    def __init__(self):
        self.max_steps = len(BET_SEQUENCE)
        self.state_file = "data/martingale_state.json"
        
    def _load(self, coin):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    return data.get(coin, 0)
            except Exception:
                pass
        return 0
        
    def _save(self, coin, step):
        data = {}
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
            except Exception:
                pass
        data[coin] = step
        with open(self.state_file, "w") as f:
            json.dump(data, f)

    def get_bet(self, coin):
        step = self._load(coin)
        amount = BET_SEQUENCE[step]
        return amount

    def win(self, coin):
        logging.info(f"[{coin}] Martingale Win. Resetting step.")
        self._save(coin, 0)

    def lose(self, coin):
        step = self._load(coin)
        if step < self.max_steps - 1:
            step += 1
            logging.info(f"[{coin}] Martingale Loss. Increasing to step {step}.")
        else:
            logging.warning(f"[{coin}] Martingale Max Steps ({self.max_steps}) Reached! Resetting to base.")
            step = 0 
        self._save(coin, step)

    def get_step(self, coin):
        return self._load(coin)
