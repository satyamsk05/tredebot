import sys
import os

# Speed hack: Free performance for Linux/AWS (Free speed)
try:
    import uvloop
    uvloop.install()
except (ImportError, AttributeError):
    pass # Windows doesn't support uvloop, default asyncio loop is used

# Ensure the root directory is on the path so `app` can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio

if __name__ == '__main__':
    from app.main import bot_loop
    asyncio.run(bot_loop())
