import discord
from discord import app_commands
import os
import json
import asyncio
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get tokens from .env file
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CMC_API_KEY = os.getenv("CMC_API_KEY")

# Initialize Discord client
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Data storage
DATA_FILE = "crypto_bot_data.json"

# Stylesheet storage
STYLES_FILE = "crypto_bot_styles.json"

# Default config structure
default_config = {
    "guilds": {}
}

# Default styles structure
default_styles = {
    "price_up_icon": "📈",
    "price_down_icon": "📉",
}

CONFIG = {}
STYLES = {}


def load_styles(path: str, defaults: dict) -> dict:
    '''
    Load style data from JSON or give reasonable defaults.
    '''
    data = dict(default_styles)
    data.update(load_json(STYLES_FILE))
    return data


def load_config() -> dict:
    '''
    Load bot data from JSON or give reasonable defaults.
    '''
    data = dict(default_config)
    data.update(load_json(DATA_FILE))
    return data


def load_json(path: str) -> dict:
    '''
    Load data from JSON file or fail quietly and return empty dict.
    '''
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Save data to JSON file
def save_config(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# Fetch crypto data from CoinMarketCap
async def fetch_crypto_data(symbols):
    if not symbols:
        return {}
    
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accept": "application/json"
    }
    params = {
        "symbol": ",".join(symbols)
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        return data["data"]
    except Exception as e:
        print(f"Error fetching crypto data: {e}")
        return {}

# Format current time in UTC
def get_utc_time():
    now = datetime.now(timezone.utc)
    return now.strftime("%I:%M %p UTC")

# Check if user has admin permissions
def is_admin(interaction):
    return interaction.user.guild_permissions.administrator

@client.event
async def on_ready():
    await tree.sync()
    print(f"{client.user} is connected to Discord!")
    
    # Start update loops
    client.loop.create_task(update_voice_channels_loop())
    client.loop.create_task(update_message_tickers_loop())

# Voice channel update loop (hourly)
async def update_voice_channels_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        await update_all_voice_channels()
        await asyncio.sleep(3600)  # 1 hour

# Message update loop (30 minutes)
async def update_message_tickers_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        await update_all_message_tickers()
        await asyncio.sleep(1800)  # 30 minutes

# Update all voice channels with current prices
async def update_all_voice_channels():
    for guild_id, guild_data in CONFIG["guilds"].items():
        if "update_category" not in guild_data or "voice_tickers" not in guild_data:
            continue
            
        guild = client.get_guild(int(guild_id))
        if not guild:
            continue
            
        category_id = guild_data["update_category"]
        category = discord.utils.get(guild.categories, id=int(category_id))
        if not category:
            continue
            
        tickers = guild_data["voice_tickers"]
        if not tickers:
            continue
            
        crypto_data = await fetch_crypto_data(tickers)
        if not crypto_data:
            continue
        
        # Sort tickers by market cap
        ticker_data = []
        for ticker in tickers:
            if ticker in crypto_data:
                price = crypto_data[ticker][0]["quote"]["USD"]["price"]
                percent_change_1h = crypto_data[ticker][0]["quote"]["USD"]["percent_change_1h"]
                market_cap = crypto_data[ticker][0]["quote"]["USD"]["market_cap"]
                ticker_data.append({
                    "symbol": ticker,
                    "price": price,
                    "percent_change_1h": percent_change_1h,
                    "market_cap": market_cap
                })
        
        # Sort by market cap (highest first)
        ticker_data.sort(key=lambda x: x["market_cap"], reverse=True)
        
        # Delete all existing voice channels in the category
        for channel in category.voice_channels:
            await channel.delete()
        
        # Create new channels with updated prices
        current_time = get_utc_time()
        for ticker_info in ticker_data:
            ticker = ticker_info["symbol"]
            price = ticker_info["price"]
            percent_change_1h = ticker_info["percent_change_1h"]
            emoji = "📈" if percent_change_1h >= 0 else "📉"
            
            # Format price based on its value
            if price < 0.01:
                price_str = f"${price:.6f}"
            elif price < 1:
                price_str = f"${price:.4f}"
            elif price < 1000:
                price_str = f"${price:.2f}"
            else:
                price_str = f"${price:.0f}"
            
            channel_name = f"{ticker} {price_str} {emoji}({current_time})"
            await category.create_voice_channel(name=channel_name)

# Update all message tickers
async def update_all_message_tickers():
    for guild_id, guild_data in CONFIG["guilds"].items():
        guild = client.get_guild(int(guild_id))
        if not guild:
            continue
        
        # Regular ticker messages
        if "message_tickers" in guild_data:
            message_tickers = guild_data["message_tickers"]
            if message_tickers:
                symbols = list(message_tickers.keys())
                crypto_data = await fetch_crypto_data(symbols)
                
                for ticker, channel_id in message_tickers.items():
                    if ticker in crypto_data:
                        channel = client.get_channel(int(channel_id))
                        if channel:
                            name = crypto_data[ticker][0]["name"]
                            price = crypto_data[ticker][0]["quote"]["USD"]["price"]
                            slug = crypto_data[ticker][0]["slug"]
                            cmc_url = f"<https://coinmarketcap.com/currencies/{slug}/>"
                            message = f"The price of {name} ({ticker}) is {price:.2f} USD on [CMC]({cmc_url})"
                            await channel.send(message)
        
        # Ratio ticker messages
        if "ratio_tickers" in guild_data:
            ratio_tickers = guild_data["ratio_tickers"]
            
            for pair, channel_id in ratio_tickers.items():
                ticker1, ticker2 = pair.split(":")
                crypto_data = await fetch_crypto_data([ticker1, ticker2])
                
                if ticker1 in crypto_data and ticker2 in crypto_data:
                    channel = client.get_channel(int(channel_id))
                    if channel:
                        price1 = crypto_data[ticker1][0]["quote"]["USD"]["price"]
                        price2 = crypto_data[ticker2][0]["quote"]["USD"]["price"]
                        ratio = price2 / price1
                        slug1 = crypto_data[ticker1][0]["slug"]
                        cmc_url = f"<https://coinmarketcap.com/currencies/{slug1}/>"
                        message = f"The swap rate of {ticker1}:{ticker2} is {ratio:.0f}:1 on [CMC]({cmc_url})"
                        await channel.send(message)

@tree.command(name="set_voice_update_category", description="Set the category for price update voice channels")
async def set_voice_update_category(interaction, category_id: str):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    try:
        category_id = int(category_id)
        guild_id = str(interaction.guild_id)
        
        # Verify the category exists
        category = discord.utils.get(interaction.guild.categories, id=category_id)
        if not category:
            await interaction.response.send_message("Category not found. Please provide a valid category ID.", ephemeral=True)
            return
        
        # Update data
        if guild_id not in CONFIG["guilds"]:
            CONFIG["guilds"][guild_id] = {}
        
        CONFIG["guilds"][guild_id]["update_category"] = category_id
        if "voice_tickers" not in CONFIG["guilds"][guild_id]:
            CONFIG["guilds"][guild_id]["voice_tickers"] = []
        
        save_config(CONFIG)
        await interaction.response.send_message(f"Update category set to {category.name}", ephemeral=True)
    
    except ValueError:
        await interaction.response.send_message("Please provide a valid category ID (numbers only).", ephemeral=True)

@tree.command(name="add_voice_ticker", description="Add a ticker to voice channel updates")
async def add_voice_ticker(interaction, ticker: str):
    # Defer the response immediately to prevent timeout
    await interaction.response.defer(ephemeral=True)
    
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.followup.send("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    ticker = ticker.upper()
    guild_id = str(interaction.guild_id)
    
    if guild_id not in CONFIG["guilds"] or "update_category" not in CONFIG["guilds"][guild_id]:
        await interaction.followup.send("Please set an update category first using /set_update_category", ephemeral=True)
        return
    
    # Verify the ticker exists
    crypto_data = await fetch_crypto_data([ticker])
    if ticker not in crypto_data:
        await interaction.followup.send(f"Ticker {ticker} not found on CoinMarketCap.", ephemeral=True)
        return
    
    if "voice_tickers" not in CONFIG["guilds"][guild_id]:
        CONFIG["guilds"][guild_id]["voice_tickers"] = []
    
    if ticker not in CONFIG["guilds"][guild_id]["voice_tickers"]:
        CONFIG["guilds"][guild_id]["voice_tickers"].append(ticker)
        save_config(CONFIG)
        
        # Force update the voice channels
        await update_all_voice_channels()
        await interaction.followup.send(f"Added {ticker} to voice channel updates.", ephemeral=True)
    else:
        await interaction.followup.send(f"{ticker} is already being tracked.", ephemeral=True)

@tree.command(name="remove_voice_ticker", description="Remove a ticker from voice channel updates")
async def remove_voice_ticker(interaction, ticker: str):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    ticker = ticker.upper()
    guild_id = str(interaction.guild_id)
    
    if guild_id in CONFIG["guilds"] and "voice_tickers" in CONFIG["guilds"][guild_id]:
        if ticker in CONFIG["guilds"][guild_id]["voice_tickers"]:
            CONFIG["guilds"][guild_id]["voice_tickers"].remove(ticker)
            save_config(CONFIG)
            
            # Force update to remove the channel
            await update_all_voice_channels()
            await interaction.response.send_message(f"Removed {ticker} from voice channel updates.", ephemeral=True)
            return
    
    await interaction.response.send_message(f"{ticker} is not currently being tracked.", ephemeral=True)

@tree.command(name="force_update_tickers", description="Force update all voice channels")
async def force_update_tickers(interaction):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    await interaction.response.send_message("Updating all voice channels...", ephemeral=True)
    await update_all_voice_channels()

@tree.command(name="add_message_ticker", description="Add a ticker for regular price messages")
async def add_message_ticker(interaction, ticker: str, channel_id: str):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    ticker = ticker.upper()
    guild_id = str(interaction.guild_id)
    
    try:
        channel_id = int(channel_id)
        channel = client.get_channel(channel_id)
        
        if not channel:
            await interaction.response.send_message("Channel not found. Please provide a valid channel ID.", ephemeral=True)
            return
        
        # Verify the ticker exists
        crypto_data = await fetch_crypto_data([ticker])
        if ticker not in crypto_data:
            await interaction.response.send_message(f"Ticker {ticker} not found on CoinMarketCap.", ephemeral=True)
            return
        
        if guild_id not in CONFIG["guilds"]:
            CONFIG["guilds"][guild_id] = {}
        
        if "message_tickers" not in CONFIG["guilds"][guild_id]:
            CONFIG["guilds"][guild_id]["message_tickers"] = {}
        
        CONFIG["guilds"][guild_id]["message_tickers"][ticker] = channel_id
        save_config(CONFIG)
        
        await interaction.response.send_message(f"Added {ticker} price messages to <#{channel_id}>", ephemeral=True)
    
    except ValueError:
        await interaction.response.send_message("Please provide a valid channel ID (numbers only).", ephemeral=True)

@tree.command(name="remove_message_ticker", description="Remove a ticker from regular price messages")
async def remove_message_ticker(interaction, ticker: str):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    ticker = ticker.upper()
    guild_id = str(interaction.guild_id)
    
    if guild_id in CONFIG["guilds"] and "message_tickers" in CONFIG["guilds"][guild_id]:
        if ticker in CONFIG["guilds"][guild_id]["message_tickers"]:
            del CONFIG["guilds"][guild_id]["message_tickers"][ticker]
            save_config(CONFIG)
            await interaction.response.send_message(f"Removed {ticker} from price messages.", ephemeral=True)
            return
    
    await interaction.response.send_message(f"{ticker} is not currently being tracked for messages.", ephemeral=True)

@tree.command(name="add_message_ratio_tickers", description="Add a ticker ratio for regular messages")
async def add_message_ratio_tickers(interaction, ticker1: str, ticker2: str, channel_id: str):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    ticker1 = ticker1.upper()
    ticker2 = ticker2.upper()
    guild_id = str(interaction.guild_id)
    
    try:
        channel_id = int(channel_id)
        channel = client.get_channel(channel_id)
        
        if not channel:
            await interaction.response.send_message("Channel not found. Please provide a valid channel ID.", ephemeral=True)
            return
        
        # Verify the tickers exist
        crypto_data = await fetch_crypto_data([ticker1, ticker2])
        if ticker1 not in crypto_data or ticker2 not in crypto_data:
            await interaction.response.send_message(f"One or both tickers not found on CoinMarketCap.", ephemeral=True)
            return
        
        if guild_id not in CONFIG["guilds"]:
            CONFIG["guilds"][guild_id] = {}
        
        if "ratio_tickers" not in CONFIG["guilds"][guild_id]:
            CONFIG["guilds"][guild_id]["ratio_tickers"] = {}
        
        pair_key = f"{ticker1}:{ticker2}"
        CONFIG["guilds"][guild_id]["ratio_tickers"][pair_key] = channel_id
        save_config(CONFIG)
        
        await interaction.response.send_message(f"Added {ticker1}:{ticker2} ratio messages to <#{channel_id}>", ephemeral=True)
    
    except ValueError:
        await interaction.response.send_message("Please provide a valid channel ID (numbers only).", ephemeral=True)

@tree.command(name="remove_message_ratio_tickers", description="Remove a ticker ratio from regular messages")
async def remove_message_ratio_tickers(interaction, ticker1: str, ticker2: str):
    # Defer the response immediately to prevent timeout
    await interaction.response.defer(ephemeral=True)
    
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.followup.send("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    ticker1 = ticker1.upper()
    ticker2 = ticker2.upper()
    pair_key = f"{ticker1}:{ticker2}"
    guild_id = str(interaction.guild_id)
    
    if guild_id in CONFIG["guilds"] and "ratio_tickers" in CONFIG["guilds"][guild_id]:
        if pair_key in CONFIG["guilds"][guild_id]["ratio_tickers"]:
            del CONFIG["guilds"][guild_id]["ratio_tickers"][pair_key]
            save_config(CONFIG)
            await interaction.followup.send(f"Removed {ticker1}:{ticker2} ratio from price messages.", ephemeral=True)
            return
    
    await interaction.followup.send(f"Ratio {ticker1}:{ticker2} is not currently being tracked.", ephemeral=True)

@tree.command(name="force_update_message_tickers", description="Force update all message tickers")
async def force_update_message_tickers(interaction):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    await interaction.response.send_message("Updating all message tickers...", ephemeral=True)
    
    # Update only the regular message tickers
    for guild_id, guild_data in CONFIG["guilds"].items():
        guild = client.get_guild(int(guild_id))
        if not guild:
            continue
        
        if "message_tickers" in guild_data:
            message_tickers = guild_data["message_tickers"]
            if message_tickers:
                symbols = list(message_tickers.keys())
                crypto_data = await fetch_crypto_data(symbols)
                
                for ticker, channel_id in message_tickers.items():
                    if ticker in crypto_data:
                        channel = client.get_channel(int(channel_id))
                        if channel:
                            name = crypto_data[ticker][0]["name"]
                            price = crypto_data[ticker][0]["quote"]["USD"]["price"]
                            slug = crypto_data[ticker][0]["slug"]
                            cmc_url = f"https://coinmarketcap.com/currencies/{slug}/"
                            message = f"The price of {name} ({ticker}) is {price:.2f} USD on [CMC]({cmc_url})"
                            await channel.send(message)

@tree.command(name="force_update_ratio_tickers", description="Force update all ratio tickers")
async def force_update_ratio_tickers(interaction):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    await interaction.response.send_message("Updating all ratio tickers...", ephemeral=True)
    
    # Update only the ratio tickers
    for guild_id, guild_data in CONFIG["guilds"].items():
        guild = client.get_guild(int(guild_id))
        if not guild:
            continue
        
        if "ratio_tickers" in guild_data:
            ratio_tickers = guild_data["ratio_tickers"]
            
            for pair, channel_id in ratio_tickers.items():
                ticker1, ticker2 = pair.split(":")
                crypto_data = await fetch_crypto_data([ticker1, ticker2])
                
                if ticker1 in crypto_data and ticker2 in crypto_data:
                    channel = client.get_channel(int(channel_id))
                    if channel:
                        price1 = crypto_data[ticker1][0]["quote"]["USD"]["price"]
                        price2 = crypto_data[ticker2][0]["quote"]["USD"]["price"]
                        ratio = price2 / price1
                        slug1 = crypto_data[ticker1][0]["slug"]
                        cmc_url = f"https://coinmarketcap.com/currencies/{slug1}/"
                        message = f"The swap rate of {ticker1}:{ticker2} is {ratio:.0f}:1 on [CMC]({cmc_url})"
                        await channel.send(message)

@tree.command(name="show_settings", description="Show all current bot settings")
async def show_settings(interaction):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    guild_id = str(interaction.guild_id)
    
    # Create embed
    embed = discord.Embed(
        title="Crypto Bot Settings",
        description=f"Current settings for {interaction.guild.name}",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    # Add bot icon as thumbnail if available
    if client.user.avatar:
        embed.set_thumbnail(url=client.user.avatar.url)
    
    # Check if guild has any settings
    if guild_id not in CONFIG["guilds"]:
        embed.add_field(name="Status", value="No settings configured yet.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    guild_data = CONFIG["guilds"][guild_id]
    
    # Add update category info
    if "update_category" in guild_data:
        category_id = guild_data["update_category"]
        category = discord.utils.get(interaction.guild.categories, id=int(category_id))
        category_name = category.name if category else "Unknown (category may have been deleted)"
        
        embed.add_field(
            name="Update Category",
            value=f"**Name:** {category_name}\n**ID:** {category_id}",
            inline=False
        )
    
    # Add voice tickers
    if "voice_tickers" in guild_data and guild_data["voice_tickers"]:
        tickers_list = ", ".join(guild_data["voice_tickers"])
        
        embed.add_field(
            name="Voice Channel Tickers",
            value=f"{tickers_list}",
            inline=False
        )
    else:
        embed.add_field(
            name="Voice Channel Tickers",
            value="None configured",
            inline=False
        )
    
    # Add message tickers
    if "message_tickers" in guild_data and guild_data["message_tickers"]:
        tickers_text = ""
        for ticker, channel_id in guild_data["message_tickers"].items():
            channel = interaction.guild.get_channel(int(channel_id))
            channel_name = channel.name if channel else "Unknown channel"
            tickers_text += f"**{ticker}** → #{channel_name} ({channel_id})\n"
        
        embed.add_field(
            name="Message Tickers",
            value=tickers_text,
            inline=False
        )
    else:
        embed.add_field(
            name="Message Tickers",
            value="None configured",
            inline=False
        )
    
    # Add ratio tickers
    if "ratio_tickers" in guild_data and guild_data["ratio_tickers"]:
        ratio_text = ""
        for pair, channel_id in guild_data["ratio_tickers"].items():
            channel = interaction.guild.get_channel(int(channel_id))
            channel_name = channel.name if channel else "Unknown channel"
            ratio_text += f"**{pair}** → #{channel_name} ({channel_id})\n"
        
        embed.add_field(
            name="Ratio Tickers",
            value=ratio_text,
            inline=False
        )
    else:
        embed.add_field(
            name="Ratio Tickers",
            value="None configured",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Run the bot
client.run(DISCORD_TOKEN)
