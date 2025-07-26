# Discord Cryptocurrency Price Bot

A modern Discord bot for live cryptocurrency price updates, price alerts, and ratio/conversion tracking, powered by the CoinMarketCap API.

## Features

- **Voice Channel Price Tickers:**  
  Dynamically creates and updates voice channels labeled with crypto symbols, prices, and movement indicators (📈/📉).
- **Scheduled Text Price Updates:**  
  Sends regular, clock-aligned price updates to designated text channels.
- **Ratio/Conversion Tracking:**  
  Tracks and posts pairwise swap/conversion rates between any two tokens.
- **Per-server Configuration:**  
  Each server sets its own CMC API key, roles, tickers, update channels, etc.
- **Slash Command Management:**  
  All admin/configuration via `/slash` commands for ease and security.
- **Exact-Timing Updates:**  
  Updates are precisely scheduled for :00 or :30 boundaries.

## Requirements

- Python 3.9+
- [discord.py](https://pypi.org/project/discord/) (`discord==2.3.2`)
- [requests](https://pypi.org/project/requests/)
- [python-dotenv](https://pypi.org/project/python-dotenv/)
- [colorlog](https://pypi.org/project/colorlog/)
- A Discord Bot token ([guide](https://discord.com/developers/applications))
- A [CoinMarketCap API Key](https://coinmarketcap.com/api/)

## Installation

1. Clone this repository:
    ```
    git clone <your-repo-url>
    cd <repo-folder>
    ```
2. (Recommended) Setup a virtual environment:
    ```
    python -m venv venv
    . venv/bin/activate
    ```
3. Install dependencies:
    ```
    pip install .
    ```

## Configuration

1. Create a `.env` in your root folder:
    ```
    DISCORD_BOT_TOKEN=your_bot_token
    ```
   *(CMC API keys are configured per-guild in Discord using the `/set_cmc_api_key` command)*

## Running the Bot

Start the bot with:

```
python -m bot
```
or just:
```
python bot.py
```

## Usage (Slash Commands Summary)

> All commands are available as Discord "slash" commands (start typing `/` in your server).

### Admin/Setup

- `/set_cmc_api_key <api_key>` &mdash; Set your guild's CMC API key (required for price lookups)
- `/remove_cmc_api_key` &mdash; Remove CMC API key for this guild
- `/set_admin_role <role_id>` &mdash; Restrict admin commands to a role ID (optional)
- `/remove_admin_role` &mdash; Remove custom admin role (admins always allowed)

### Voice Ticker Channels

- `/set_voice_update_category <category_id>` &mdash; Designate a category for voice tickers
- `/add_voice_ticker <ticker>` &mdash; Track a crypto symbol in voice
- `/remove_voice_ticker <ticker>` &mdash; Untrack a symbol in voice

### Regular Message Price Updates

- `/add_message_ticker <ticker> <channel_id>` &mdash; Add a symbol to text updates in given channel
- `/remove_message_ticker <ticker>` &mdash; Remove symbol from text updates

### Ratio/Pair Tracking

- `/add_message_ratio_tickers <ticker1> <ticker2> <channel_id>` &mdash; Add a pair (A:B) to track conversion rates
- `/remove_message_ratio_tickers <ticker1> <ticker2>` &mdash; Remove pair

### Utilities

- `/show_settings` &mdash; Show current settings/status overview for your guild
- `/force_update_voice_tickers` &mdash; Immediately refresh all voice price channels
- `/force_update_message_tickers` &mdash; Immediately refresh all price message tickers
- `/force_update_ratio_tickers` &mdash; Immediately refresh all ratio tickers

---

## How the Bot Works

- **Voice Price Channels:**  
  At the top of each hour, all configured voice ticker channels are deleted & recreated, showing the latest price and movement.
- **Message Updates:**  
  Every 30 minutes, posts the current price or conversion rate to configured text channels.
- **CMC API Calls:**  
  CoinMarketCap API requests are live and cached, and all coin references link directly to [CMC currency pages](https://coinmarketcap.com/).
- **Data Storage:**  
  Per-server (guild) settings are stored in `crypto_bot_data.json`. Custom style/emoji in `crypto_bot_styles.json` (optional).
- **Security:**  
  Only Discord admins or those with a configured admin role can change settings.

---

## Notes

- **Discord Permissions Required:**  
  - "View Channels", "Manage Channels" (to create/delete voice tickers)
  - "Send Messages", "Embed Links" for target text channels

- **CoinMarketCap Free API Limits:**  
  Each key gets 10,000 monthly credits (sufficient for most uses).

- **Customization:**  
  Emoji/icons can be changed via `crypto_bot_styles.json` (see the code for details).

---

## License

MIT License.
