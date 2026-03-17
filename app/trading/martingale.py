import json
import os
import logging

# Strict Martingale Sequence: 3-6-13-28-60
BET_SEQUENCE = [3, 6, 13, 28, 60]

CONFIG_FILE = "data/ui_config.json"

class Martingale:
    def __init__(self):
        self.state_file = "data/martingale_state.json"
        
    def _get_active_sequence(self):
        """Returns the fixed bet sequence."""
        return BET_SEQUENCE

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
        seq = self._get_active_sequence()
        # Security bound
        if step >= len(seq): 
            step = 0
            self._save(coin, step)
        return seq[step]

    def win(self, coin):
        logging.info(f"[{coin}] Martingale Win. Resetting step.")
        self._save(coin, 0)

    def lose(self, coin):
        step = self._load(coin)
        seq = self._get_active_sequence()
        max_steps = len(seq)
        
        if step < max_steps - 1:
            step += 1
            logging.info(f"[{coin}] Martingale Loss. Increasing to step {step}.")
        else:
            logging.warning(f"[{coin}] Martingale Max Steps ({max_steps}) Reached! Resetting to base.")
            step = 0 
        self._save(coin, step)

    def get_step(self, coin):
        return self._load(coin)

    def get_max_steps(self):
        return len(self._get_active_sequence())
