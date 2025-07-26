import asyncio
import os
import logging
import time
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import (
    GuildConfiguration, Configuration, ConfigManager, StyleManager,
    format_price
)
from quote import PriceQuoteCache

# ============== LOGGING SETUP ==================
import colorlog

log_colors = {
    'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow',
    'ERROR': 'red', 'CRITICAL': 'bold_red',
}
formatter = colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s.%(msecs)03d %(name)-12s [%(levelname)-8s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    log_colors=log_colors,
)
logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logging.getLogger().handlers.clear()
logging.getLogger().addHandler(console_handler)
logging.getLogger().setLevel(logging.INFO)
for comp in ['discord', 'discord.client', 'discord.gateway']:
    logging.getLogger(comp).setLevel(logging.INFO)
logging.getLogger('discord.http').setLevel(logging.WARNING)

# ============== CONFIG/STARTUP ==================
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
config_mgr, style_mgr = ConfigManager(), StyleManager()
Config: Configuration = config_mgr.load_configuration()
STYLES = style_mgr.load_styles()
PriceQuoter = PriceQuoteCache()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# ============== HELPERS/DECORATORS ===============
def is_admin_check():
    """Decorator for admin role check."""
    async def predicate(ctx):
        gid = getattr(ctx.guild, "id", None) or ctx.guild_id
        user = ctx.user if hasattr(ctx, 'user') else ctx.author
        if user.guild_permissions.administrator:
            return True
        gconf = Config.guilds.get(gid)
        if gconf and gconf.admin_role_id:
            return any(getattr(r, "id", 0) == gconf.admin_role_id for r in getattr(user, "roles", []))
        await ctx.response.send_message("Admin or configured role required.", ephemeral=True)
        return False
    return commands.check(predicate)

async def verify_ticker_exists(api_key: str, ticker: str) -> bool:
    return bool(await PriceQuoter.fetch_no_cache(api_key, [ticker]))

def guild_has_api_key(guild_id: int) -> bool:
    g = Config.guilds.get(guild_id)
    return bool(g and g.cmc_api_key)

def get_guild_conf(ctx) -> Optional[GuildConfiguration]:
    gid = getattr(ctx.guild, "id", None) or ctx.guild_id
    return Config.guilds.get(gid)

# ================ UPDATE/UTILITY ================
async def update_voice_channels():
    logger.info("🎤 Voice updates for all guilds")
    for g in Config.guilds.values():
        if not (g.update_category and g.voice_tickers and g.cmc_api_key):
            continue
        guild = bot.get_guild(g.id)
        cat = discord.utils.get(guild.categories, id=g.update_category) if guild else None
        if not (guild and cat): continue
        quotes = await PriceQuoter.fetch(g.cmc_api_key, g.voice_tickers, time.time())
        sorted_quotes = sorted(quotes, key=lambda q: q.market_cap or 0, reverse=True)
        # Remove all existing, then create
        for ch in list(cat.voice_channels): await ch.delete()
        for q in sorted_quotes:
            emoji = STYLES['price_up_icon'] if q.percent_change_1h >= 0 else STYLES['price_down_icon']
            await cat.create_voice_channel(name=f"{q.symbol} {emoji} {format_price(q.price_usd)}")

async def update_message_tickers(regular: bool = True, ratio: bool = True):
    for g in Config.guilds.values():
        if not g.cmc_api_key: continue
        guild = bot.get_guild(g.id)
        if not guild: continue
        if regular and g.message_tickers: await update_regular_tickers(g, guild)
        if ratio and g.ratio_tickers: await update_ratio_tickers(g, guild)

async def update_regular_tickers(g: GuildConfiguration, guild):
    syms = list(g.message_tickers.keys())
    quotes = await PriceQuoter.fetch(g.cmc_api_key, syms, time.time())
    q_by_sym = {q.symbol: q for q in quotes}
    for sym, cid in g.message_tickers.items():
        ch = guild.get_channel(cid)
        if not (ch and q_by_sym.get(sym)): continue
        q = q_by_sym[sym]
        url = f"<https://coinmarketcap.com/currencies/{q.slug}/>"
        await ch.send(
            f"The price of {q.name} ({sym}) is ${q.price_usd:.2f} USD on [CMC]({url})"
        )

async def update_ratio_tickers(g: GuildConfiguration, guild):
    for pair, cid in g.ratio_tickers.items():
        t1, t2 = pair.split(":")
        quotes = await PriceQuoter.fetch(g.cmc_api_key, [t1, t2], time.time())
        qd = {q.symbol: q for q in quotes}
        if t1 in qd and t2 in qd:
            ch = guild.get_channel(cid)
            base_q = qd[t2]  # CMC URL for the base in the ratio (as before)
            url = f"<https://coinmarketcap.com/currencies/{base_q.slug}/>"
            try:
                ratio = int(qd[t2].price_usd / qd[t1].price_usd)
            except (ZeroDivisionError, TypeError):
                ratio = "N/A"
            await ch.send(
                f"The swap rate of {t1}:{t2} is {ratio}:1 on [CMC]({url})"
            )

# ============ CLOCK-BOUNDARY UPDATE LOOPS ============
async def wait_for_boundary(interval: int, name: str):
    """Wait until the next time boundary for consistent scheduling."""
    now = time.time()
    next_boundary = interval - (now % interval)
    logger.info("⏰ Waiting %.1f seconds until next %s update", next_boundary, name)
    await asyncio.sleep(next_boundary)
    # Wait for bot connection if disconnected
    while bot.is_closed():
        logger.warning("⚠️  Client disconnected, retrying %s update in 3 minutes", name)
        await asyncio.sleep(180)

async def voice_update_loop():
    """Main loop for updating voice channels every hour at :00."""
    logger.info("🎤 Voice update loop initialized")
    await bot.wait_until_ready()
    while True:
        await wait_for_boundary(3600, "voice channel")
        await update_voice_channels()

async def message_update_loop():
    """Main loop for updating message tickers every 30m at :00 or :30."""
    logger.info("💬 Message update loop initialized")
    await bot.wait_until_ready()
    while True:
        await wait_for_boundary(1800, "message ticker")
        await update_message_tickers()

# ============== COMMANDS / SLASH TREE ===============
@tree.command(name="set_cmc_api_key", description="Set this server's CMC API key")
@is_admin_check()
async def set_cmc_api_key(ctx, api_key: str):
    """Set API key, validate, store."""
    api_key = api_key.strip()
    if len(api_key) < 10 or not await verify_ticker_exists(api_key, "BTC"):
        await ctx.response.send_message("Invalid or unaccepted API key.", ephemeral=True)
        return
    g = Config.get_or_create_guild(ctx.guild_id)
    g.cmc_api_key = api_key
    config_mgr.save_configuration(Config)
    await ctx.response.send_message("API key saved and validated.", ephemeral=True)

@tree.command(name="remove_cmc_api_key", description="Remove CMC API key")
@is_admin_check()
async def remove_cmc_api_key(ctx):
    g = get_guild_conf(ctx)
    if g and g.cmc_api_key:
        g.cmc_api_key = None
        config_mgr.save_configuration(Config)
        await ctx.response.send_message("API key removed.", ephemeral=True)
    else:
        await ctx.response.send_message("No API key set.", ephemeral=True)

@tree.command(name="set_admin_role", description="Set admin role")
@is_admin_check()
async def set_admin_role(ctx, role_id: str):
    try:
        role = ctx.guild.get_role(int(role_id))
        if not role: raise ValueError
        g = Config.get_or_create_guild(ctx.guild_id)
        g.admin_role_id = role.id
        config_mgr.save_configuration(Config)
        await ctx.response.send_message(
            f"Admin role set to {role.mention}.", ephemeral=True)
    except:
        await ctx.response.send_message("Invalid role ID.", ephemeral=True)

@tree.command(name="set_voice_update_category", description="Set update category for voice tickers")
@is_admin_check()
async def set_voice_update_category(ctx, category_id: str):
    try:
        cat = discord.utils.get(ctx.guild.categories, id=int(category_id))
        if not cat: raise ValueError
        g = Config.get_or_create_guild(ctx.guild_id)
        g.update_category = cat.id
        g.voice_tickers.clear()
        config_mgr.save_configuration(Config)
        await ctx.response.send_message(f"Update category set to **{cat.name}**", ephemeral=True)
    except:
        await ctx.response.send_message("Invalid category ID.", ephemeral=True)

@tree.command(name="add_voice_ticker", description="Add a voice price ticker")
@is_admin_check()
async def add_voice_ticker(ctx, ticker: str):
    ticker = ticker.upper()
    g = get_guild_conf(ctx)
    if not (g and g.update_category and g.cmc_api_key):
        await ctx.response.send_message(
            "Set update category and CMC API key first.", ephemeral=True
        )
        return
    if not await verify_ticker_exists(g.cmc_api_key, ticker):
        await ctx.response.send_message(f"Ticker {ticker} not found.", ephemeral=True)
        return
    if ticker not in g.voice_tickers:
        g.voice_tickers.append(ticker)
        config_mgr.save_configuration(Config)
        await update_voice_channels()
        await ctx.response.send_message(f"Added {ticker} to updates.", ephemeral=True)
    else:
        await ctx.response.send_message(f"{ticker} already tracked.", ephemeral=True)

@tree.command(name="remove_voice_ticker", description="Remove voice ticker")
@is_admin_check()
async def remove_voice_ticker(ctx, ticker: str):
    ticker = ticker.upper()
    g = get_guild_conf(ctx)
    if g and ticker in g.voice_tickers:
        g.voice_tickers.remove(ticker)
        config_mgr.save_configuration(Config)
        await update_voice_channels()
        await ctx.response.send_message(f"Removed {ticker}.", ephemeral=True)
    else:
        await ctx.response.send_message(f"{ticker} not tracked.", ephemeral=True)

@tree.command(name="add_message_ticker", description="Add message price updates")
@is_admin_check()
async def add_message_ticker(ctx, ticker: str, channel_id: str):
    ticker, cid = ticker.upper(), int(channel_id)
    g = get_guild_conf(ctx)
    ch = ctx.guild.get_channel(cid)
    if not (g and g.cmc_api_key and ch):
        await ctx.response.send_message("Check API key and channel.", ephemeral=True)
        return
    if not await verify_ticker_exists(g.cmc_api_key, ticker):
        await ctx.response.send_message(f"Ticker {ticker} not found.", ephemeral=True)
        return
    g.message_tickers[ticker] = cid
    config_mgr.save_configuration(Config)
    await ctx.response.send_message(f"Added {ticker} to #{ch.name}.", ephemeral=True)

@tree.command(name="add_message_ratio_tickers", description="Add a ticker ratio for messages")
@is_admin_check()
async def add_message_ratio_tickers(ctx, ticker1: str, ticker2: str, channel_id: str):
    t1, t2, cid = ticker1.upper(), ticker2.upper(), int(channel_id)
    g = get_guild_conf(ctx)
    ch = ctx.guild.get_channel(cid)
    if not (g and g.cmc_api_key and ch):
        await ctx.response.send_message("Check API key and channel.", ephemeral=True)
        return
    data = await PriceQuoter.fetch_no_cache(g.cmc_api_key, [t1, t2])
    have = {q.symbol for q in data}
    if t1 not in have or t2 not in have:
        await ctx.response.send_message(f"One or both tickers invalid.", ephemeral=True)
        return
    g.ratio_tickers[f"{t1}:{t2}"] = cid
    config_mgr.save_configuration(Config)
    await ctx.response.send_message(f"Added {t1}:{t2} to #{ch.name}.", ephemeral=True)

@tree.command(name="remove_message_ticker", description="Remove a message price ticker")
@is_admin_check()
async def remove_message_ticker(ctx, ticker: str):
    ticker = ticker.upper()
    g = get_guild_conf(ctx)
    if g and ticker in g.message_tickers:
        del g.message_tickers[ticker]
        config_mgr.save_configuration(Config)
        await ctx.response.send_message(f"Removed {ticker}.", ephemeral=True)
    else:
        await ctx.response.send_message(f"{ticker} not tracked.", ephemeral=True)

@tree.command(name="remove_message_ratio_tickers", description="Remove a ratio pair from messages")
@is_admin_check()
async def remove_message_ratio_tickers(ctx, ticker1: str, ticker2: str):
    k = f"{ticker1.upper()}:{ticker2.upper()}"
    g = get_guild_conf(ctx)
    if g and k in g.ratio_tickers:
        del g.ratio_tickers[k]
        config_mgr.save_configuration(Config)
        await ctx.response.send_message(f"Removed {k}.", ephemeral=True)
    else:
        await ctx.response.send_message(f"{k} not tracked.", ephemeral=True)

@tree.command(name="show_settings", description="Show this server's config")
@is_admin_check()
async def show_settings(ctx):
    g = get_guild_conf(ctx)
    embed = discord.Embed(
        title="Crypto Bot Settings",
        description=f"Current settings for **{ctx.guild.name}**",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    if bot.user and bot.user.avatar:
        embed.set_thumbnail(url=bot.user.avatar.url)
    if not g:
        embed.add_field(name="Status", value="No settings configured.", inline=False)
    else:
        # API key
        ak = g.cmc_api_key
        api_key_disp = f"✅ ...{ak[-4:]}" if ak else "❌ Not configured"
        embed.add_field(name="CoinMarketCap API Key", value=api_key_disp, inline=False)
        # Admin role
        if g.admin_role_id:
            role = ctx.guild.get_role(g.admin_role_id)
            val = f"**{role.name}** ({g.admin_role_id})" if role else f"ID {g.admin_role_id} (deleted)"
        else:
            val = "Not configured"
        embed.add_field(name="Admin Role", value=val, inline=False)
        # Category
        if g.update_category:
            cat = discord.utils.get(ctx.guild.categories, id=g.update_category)
            cname = cat.name if cat else "Unknown (deleted)"
            embed.add_field(name="Update Category", value=f"{cname} ({g.update_category})", inline=False)
        # Tickers
        vt = ", ".join(g.voice_tickers) if g.voice_tickers else "None"
        embed.add_field(name="Voice Tickers", value=vt, inline=False)
        if g.message_tickers:
            mt = '\n'.join([f"{k}→#{ctx.guild.get_channel(cid).name if ctx.guild.get_channel(cid) else cid}" 
                            for k, cid in g.message_tickers.items()])
            embed.add_field(name="Message Tickers", value=mt, inline=False)
        if g.ratio_tickers:
            rt = '\n'.join([f"{pair}→#{ctx.guild.get_channel(cid).name if ctx.guild.get_channel(cid) else cid}" 
                            for pair, cid in g.ratio_tickers.items()])
            embed.add_field(name="Ratio Tickers", value=rt, inline=False)
    await ctx.response.send_message(embed=embed, ephemeral=True)

# Convenience force-update commands
def update_wrap(method, **kwargs):
    async def inner(ctx):
        if not guild_has_api_key(ctx.guild_id):
            await ctx.response.send_message("Set API key first.", ephemeral=True)
            return
        await ctx.response.send_message("Updating...", ephemeral=True)
        await method(**kwargs)
    return inner

tree.command(name="force_update_voice_tickers", description="Force update all voice channels")(
    is_admin_check()(update_wrap(update_voice_channels))
)
tree.command(name="force_update_message_tickers", description="Force update message tickers")(
    is_admin_check()(update_wrap(update_message_tickers, regular=True, ratio=False))
)
tree.command(name="force_update_ratio_tickers", description="Force update ratio tickers")(
    is_admin_check()(update_wrap(update_message_tickers, regular=False, ratio=True))
)

@tree.command(name="remove_admin_role", description="Remove configured admin role")
@is_admin_check()
async def remove_admin_role(ctx):
    g = get_guild_conf(ctx)
    if g and g.admin_role_id:
        g.admin_role_id = None
        config_mgr.save_configuration(Config)
        await ctx.response.send_message("Admin role removed. Only admins can use admin commands now.", ephemeral=True)
    else:
        await ctx.response.send_message("No admin role configured.", ephemeral=True)

# ============= MAIN BOT EVENT & STARTUP ======================
@bot.event
async def on_ready():
    await tree.sync()
    logger.info("Bot ready and slash commands synced")
    # Start update loops (clock-aligned)
    if not hasattr(bot, "voice_update_task"):
        bot.voice_update_task = asyncio.create_task(voice_update_loop())
    if not hasattr(bot, "message_update_task"):
        bot.message_update_task = asyncio.create_task(message_update_loop())

if __name__ == "__main__":
    logger.info("🚀 Starting Crypto Bot ...")
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except Exception as e:
        logger.critical("❌ Failed to start bot: %s", str(e))
        raise
