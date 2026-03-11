import sys
import os

# Ensure the root directory is on the path so `app` can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    from app.main import bot_loop
    bot_loop()
