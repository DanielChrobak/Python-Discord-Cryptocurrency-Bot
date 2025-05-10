# Discord Cryptocurrency Bot

A Discord bot that provides real-time cryptocurrency price tracking using the CoinMarketCap API.

## Features

- **Voice Channel Price Updates**: Creates voice channels showing current prices of cryptocurrencies
- **Automatic Price Messages**: Sends regular price updates to designated text channels
- **Price Ratio Tracking**: Monitors and reports exchange rates between cryptocurrency pairs

## Setup

1. Clone this repository
2. Install required dependencies:
```
pip install discord.py requests python-dotenv
```

3. Create a `.env` file in the root directory with the following variables:

```
DISCORD_BOT_TOKEN=your_discord_bot_token
CMC_API_KEY=your_coinmarketcap_api_key
```

4. Start the bot:
```
python bot.py
```

## Configuration Commands

`/set_update_category <category_id>` - Set the category for price update voice channels

`/force_update_tickers` - Force update all voice channels

`/force_update_message_tickers` - Force update all message tickers

`/force_update_ratio_tickers` - Force update all ratio tickers

`/show_settings` - Display all current bot settings

## Voice Channel Commands
`/add_voice_ticker <ticker>` - Add a cryptocurrency ticker to voice channel updates

`/remove_voice_ticker <ticker>` - Remove a ticker from voice channel updates

## Message Commands
`/add_message_ticker <ticker> <channel_id>` - Add a ticker for regular price messages

`/remove_message_ticker <ticker>` - Remove a ticker from regular price messages

`/add_message_ratio_tickers <ticker1> <ticker2> <channel_id>` - Add a ticker ratio for regular messages

`/remove_message_ratio_tickers <ticker1> <ticker2>` - Remove a ticker ratio from regular messages

## How It Works
The bot creates and updates voice channels with current cryptocurrency prices, including price movement indicators (📈 or 📉). It also sends regular messages to designated text channels with current prices and links to CoinMarketCap.

Price data is automatically refreshed on the following schedule:

- Voice channels: Updated hourly

- Text messages: Updated every 30 minutes

## Data Storage
The bot stores configuration data in a JSON file (crypto_bot_data.json), which includes:

- Guild-specific settings

- Voice channel tickers

- Message channel tickers

- Ratio ticker pairs

## Requirements
- Python 3.8+

- discord.py

- requests

- python-dotenv

- A Discord Bot Token

- A CoinMarketCap API Key

## License
MIT License

