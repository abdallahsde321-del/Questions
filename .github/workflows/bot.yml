name: YouTube Live Questions Monitor

on:
  schedule:
    - cron: '0 */5 * * *'
  workflow_dispatch:

jobs:
  run-bot:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Bot
        env:
          PYTHONUNBUFFERED: '1'
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          YOUTUBE_CHANNEL_HANDLE: ${{ secrets.YOUTUBE_CHANNEL_HANDLE }}
        run: python -u main.py
