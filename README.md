# Discord Cryptocurrency Bot

A Discord bot that provides real-time cryptocurrency price tracking using the CoinMarketCap API.

## Features

- **Voice Channel Price Updates**: Creates voice channels showing current prices of cryptocurrencies
- **Automatic Price Messages**: Sends regular price updates to designated text channels
- **Price Ratio Tracking**: Monitors and reports exchange rates between cryptocurrency pairs

## Setup

1. Clone this repository
2. Install required dependencies:
   ```bash
   pip install discord.py requests python-dotenv

3. Create a `.env` file in the root directory with the following variables:

```
DISCORD_BOT_TOKEN=your_discord_bot_token
CMC_API_KEY=your_coinmarketcap_api_key
```
