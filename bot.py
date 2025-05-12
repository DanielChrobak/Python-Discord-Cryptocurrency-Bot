from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
import os
import json
import asyncio
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from dataclasses import dataclass, field
import logging


logger = logging.getLogger('main')


@dataclass
class GuildConfiguration:
    id: int
    '''
    The guild's guild id.
    '''
    update_category: Optional[int] = None
    voice_tickers: List[str] = field(default_factory=list)
    ratio_tickers: Dict[str,int] = field(default_factory=dict)
    message_tickers: Dict[str, int] = field(default_factory=dict)


@dataclass
class Configuration:
    '''
    Configuration for the entire update bot.
    '''

    guilds: Dict[int,GuildConfiguration]
    '''
    Configuration for invididual servers under the bot's control. Indexed by
    guild id.
    '''


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

# Default styles structure
default_styles = {
    "price_up_icon": "📈",
    "price_down_icon": "📉",
}

Config: Configuration = None
STYLES = {}


def to_all_strings(d: Dict[str,int]) -> Dict[str,str]:
    '''
    Convert the given dictionary of strings->ints into a dictionary of
    strings->decimal-integer-strings so as to avoid data loss in JSON.
    '''
    return { k: str(v) for k, v in d.items() }


def to_all_ints(d: Dict[str,str]) -> Dict[str,int]:
    '''
    Convert the given dictionary of strings->decimal-integer-strings into a
    dictionary of strings->ints under the assumption that the former was
    in place simply to avoid JSON data loss.
    '''
    return { k: str(v) for k, v in d.items() }


def config_from_dict(d: Dict) -> Configuration:
    '''
    Produce a bot configuration struct from a dictionary loaded, presumably,
    from JSON.
    '''
    guilds_in: Dict = d.get('guilds', {})
    guilds: Dict[int,GuildConfiguration] = {}
    for guild_id_s, guild_data in guilds_in.items():
        guild_id = int(guild_id_s)
        update_category = guild_data.get('update_category')
        if update_category is not None:
            update_category = int(update_category)
        voice_tickers = guild_data.get('voice_tickers', [])
        ratio_tickers = to_all_ints(guild_data.get('ratio_tickers', {}))
        message_tickers = to_all_ints(guild_data.get('message_tickers', {}))
        guilds[guild_id] = GuildConfiguration(
            id=guild_id,
            update_category=update_category,
            voice_tickers=voice_tickers,
            ratio_tickers=ratio_tickers,
            message_tickers=message_tickers,
        )
    return Configuration(guilds=guilds)


def dict_from_config(c: Configuration) -> Dict:
    '''
    Produce a JSON-compatible dictionary from a server configuration.
    '''
    d = {}
    for guild in c.guilds.values():
        guild_data = {
            'message_tickers': to_all_strings(guild.message_tickers),
            'ratio_tickers': to_all_strings(guild.ratio_tickers),
            'voice_tickers': guild.voice_tickers,
        }
        if guild.update_category is not None:
            guild_data['update_category'] = str(guild.update_category)
        d[str(guild.id)] = guild_data
    return d


def load_styles() -> dict:
    '''
    Load style data from JSON or give reasonable defaults.
    '''
    data = dict(default_styles)
    data.update(load_json(STYLES_FILE))
    return data


def load_config() -> Configuration:
    '''
    Load bot data from JSON or give reasonable defaults.
    '''
    data = load_json(DATA_FILE)
    return config_from_dict(data)


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
def save_config(c: Configuration):
    d = dict_from_config(c)
    with open(DATA_FILE, 'w') as f:
        json.dump(d, f, indent=4)

# Fetch crypto data from CoinMarketCap
async def fetch_crypto_data(symbols: List[str]):
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
        logger.exception("Error fetching crypto data")
        return {}

# Format current time in UTC
def get_utc_time():
    now = datetime.now(timezone.utc)
    return now.strftime("%I:%M %p UTC")

# Check if user has admin permissions
def is_admin(interaction):
    return interaction.user.guild_permissions.administrator

voice_loop = None
tickers_loop = None

@client.event
async def on_connect():
    global voice_loop
    global tickers_loop
    await tree.sync()
    logger.info(f"{client.user} is connected to Discord!")
    
    # Start update loops
    voice_loop = client.loop.create_task(update_voice_channels_loop())
    tickers_loop = client.loop.create_task(update_message_tickers_loop())


@client.event
async def on_disconnect():
    logging.info(f"{client.user} is disconnected.")
    global voice_loop
    global tickers_loop
    if voice_loop is not None:
        voice_loop.cancel()
        voice_loop = None
    if tickers_loop is not None:
        tickers_loop.cancel()
        tickers_loop = None


# Voice channel update loop (hourly)
async def update_voice_channels_loop():
    await client.wait_until_ready()
    while True:
        if not client.is_closed():
            await update_all_voice_channels()
            await asyncio.sleep(3600)  # 1 hour
        else:
            await asyncio.sleep(300)

# Message update loop (30 minutes)
async def update_message_tickers_loop():
    await client.wait_until_ready()
    while True:
        if not client.is_closed():
            await update_all_message_tickers()
            await asyncio.sleep(1800)  # 30 minutes
        else:
            await asyncio.sleep(300)

# Update all voice channels with current prices
async def update_all_voice_channels():
    logging.info("Updating all voice channels")
    for guild_config in Config.guilds.values():
        if guild_config.update_category is None or not guild_config.voice_tickers:
            continue
            
        guild = client.get_guild(guild_config.id)
        if not guild:
            logging.warning("Configuration for bot lists a guild that may no longer exist: %d", guild_config.id)
            continue
            
        category_id = guild_config.update_category
        category = discord.utils.get(guild.categories, id=int(category_id))
        if not category:
            continue
            
        tickers = guild_config.voice_tickers
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
        _current_time = get_utc_time()
        for ticker_info in ticker_data:
            ticker = ticker_info["symbol"]
            price = ticker_info["price"]
            percent_change_1h = ticker_info["percent_change_1h"]
            if percent_change_1h >= 0:
                emoji = STYLES['price_up_icon']
            else:
                emoji = STYLES['price_down_icon']
            
            # Format price based on its value
            if price < 0.01:
                price_str = f"${price:.6f}"
            elif price < 1:
                price_str = f"${price:.4f}"
            elif price < 1000:
                price_str = f"${price:.2f}"
            else:
                price_str = f"${price:.0f}"
            
            logging.debug("Updating voice ticker for %s: %s", ticker, price_str)
            channel_name = f"{ticker} {price_str} {emoji}"
            await category.create_voice_channel(name=channel_name)


# Update all message tickers
async def update_all_message_tickers():
    for guild_config in Config.guilds.values():
        guild = client.get_guild(guild.id)
        if not guild:
            continue
        
        # Regular ticker messages
        message_tickers = guild_config.message_tickers
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
        ratio_tickers = guild_config.ratio_tickers            
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
        guild_id = interaction.guild_id
        
        # Verify the category exists
        category = discord.utils.get(interaction.guild.categories, id=category_id)
        if not category:
            await interaction.response.send_message("Category not found. Please provide a valid category ID.", ephemeral=True)
            return
        
        # Update data
        guild = Config.guilds.get(guild_id)
        if guild is None:
            guild = GuildConfiguration(id=guild_id)
            Config.guilds[guild_id] = guild
        
        guild.update_category = category_id
        guild.voice_tickers = []
        
        save_config(Config)
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
    guild_id = interaction.guild_id
    guild = Config.guilds.get(guild_id)
    if guild is None or guild.update_category is None:
        await interaction.followup.send("Please set an update category first using /set_update_category", ephemeral=True)
        return
    
    # Verify the ticker exists
    crypto_data = await fetch_crypto_data([ticker])
    if ticker not in crypto_data:
        await interaction.followup.send(f"Ticker {ticker} not found on CoinMarketCap.", ephemeral=True)
        return
    
    if ticker not in guild.voice_tickers:
        guild.voice_tickers.append(ticker)
        save_config(Config)
        
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
    guild_id = interaction.guild_id
    
    guild = Config.guilds.get(guild_id)
    if guild is not None:
        if ticker in guild.voice_tickers:
            guild.voice_tickers.remove(ticker)
            save_config(Config)
            
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
    guild_id = interaction.guild_id
    
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
        
        guild = Config.guilds.get(guild_id)
        if guild is None:
            guild = GuildConfiguration(id=guild_id)
            Config.guilds[guild_id] = guild
        
        guild.message_tickers[ticker] = channel_id
        save_config(Config)
        
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
    guild_id = interaction.guild_id
    guild = Config.guilds.get(guild_id)
    if guild is not None and (ticker in guild.message_tickers):
        del guild.message_tickers[ticker]
        save_config(Config)
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
    guild_id = interaction.guild_id
    
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
        
        guild = Config.guilds.get(guild_id)
        if guild is None:
            guild = GuildConfiguration(id=guild_id)
                
        pair_key = f"{ticker1}:{ticker2}"
        guild.ratio_tickers[pair_key] = channel_id
        save_config(Config)
        
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
    guild_id = interaction.guild_id
    
    guild = Config.guilds.get(guild_id)
    if guild is not None:
        if pair_key in guild.ratio_tickers:
            del guild.ratio_tickers[pair_key]
            save_config(Config)
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
    await update_all_message_tickers()


@tree.command(name="show_settings", description="Show all current bot settings")
async def show_settings(interaction):
    # Check if user has admin permissions
    if not is_admin(interaction):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
        return
    
    guild_id = interaction.guild_id
    
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
    guild = Config.guilds.get(guild_id)
    if guild is None:
        embed.add_field(name="Status", value="No settings configured yet.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
       
    # Add update category info
    if guild.update_category is not None:
        category = discord.utils.get(interaction.guild.categories, id=guild.update_category)
        category_name = category.name if category else "Unknown (category may have been deleted)"
        
        embed.add_field(
            name="Update Category",
            value=f"**Name:** {category_name}\n**ID:** {guild.update_category}",
            inline=False
        )
    
    # Add voice tickers
    voice_tickers = guild.voice_tickers
    if voice_tickers:
        tickers_list = ", ".join(voice_tickers)
        
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
    message_tickers = guild.message_tickers
    if message_tickers:
        tickers_text = ""
        for ticker, channel_id in message_tickers.items():
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
    ratio_tickers = guild.ratio_tickers
    if ratio_tickers:
        ratio_text = ""
        for pair, channel_id in ratio_tickers.items():
            channel = interaction.guild.get_channel(channel_id)
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

Config = load_config()
STYLES = load_styles()

# Run the bot
client.run(DISCORD_TOKEN)
