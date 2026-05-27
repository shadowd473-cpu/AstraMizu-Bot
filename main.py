import os
import discord
from discord.ext import commands
from openai import AsyncOpenAI, OpenAI
import chromadb
from chromadb.utils import embedding_functions
import asyncio
import aiohttp
import io
import yt_dlp
import random

# Load .env if exists
from dotenv import load_dotenv
load_dotenv()

# Make OpenAI library happy with XAI key
os.environ["OPENAI_API_KEY"] = os.getenv("XAI_API_KEY")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

XAI_KEY = os.getenv("XAI_API_KEY")

client = AsyncOpenAI(
    api_key=XAI_KEY,
    base_url="https://api.x.ai/v1"
)

sync_client = OpenAI(
    api_key=XAI_KEY,
    base_url="https://api.x.ai/v1"
)

OWNER_ID = 406054379406229504
TRIGGER_WORDS = ["astra", "mizu", "astramizu"]

# Music Queue
queues = {}
voice_clients = {}

# ChromaDB
chroma_client = chromadb.PersistentClient(path="./chroma_db")
embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = chroma_client.get_or_create_collection(name="astra_memory", embedding_function=embedding_function)

# REACTIONS
REACTION_RESPONSES = {
    "❤️": ["Aww~ Thank you! 💖", "Ehehe~ You're sweet! ❤️"],
    "😘": ["Kyaa~! 😳", "Mwah~ 💋"],
    "🔥": ["Oho~ Feeling bold? 😏"],
    "😂": ["Glad I made you laugh~ 😄"],
}

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot or reaction.message.author != bot.user: return
    emoji = str(reaction.emoji)
    if emoji in REACTION_RESPONSES:
        await reaction.message.channel.send(random.choice(REACTION_RESPONSES[emoji]))

# MAIN HANDLER - FIXED
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content_lower = message.content.lower()
    is_mentioned = bot.user.mentioned_in(message)
    has_trigger = any(word in content_lower for word in TRIGGER_WORDS)

    # Always respond if mentioned or has trigger
    if not (is_mentioned or has_trigger):
        await bot.process_commands(message)
        return

    try:
        # Simple response for now
        response = await client.chat.completions.create(
            model="grok-4",
            messages=[
                {"role": "system", "content": "You are AstraMizu, a cheerful and playful anime girl. Be cute and fun."},
                {"role": "user", "content": message.content}
            ],
            max_tokens=300,
            temperature=0.9
        )
        reply = response.choices[0].message.content
        await message.reply(reply)
    except Exception as e:
        print(f"Message error: {e}")
        await message.reply("Sorry, I'm a bit tired right now~")

    await bot.process_commands(message)

# ====================== MUSIC SYSTEM ======================

def get_ydl_opts():
    return {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'extractor_args': {'youtube': {'player_client': ['ios', 'web']}},
    }

async def play_next(ctx):
    if ctx.guild.id not in queues or not queues[ctx.guild.id]:
        return

    url = queues[ctx.guild.id].pop(0)
    try:
        vc = voice_clients[ctx.guild.id]

        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            url2 = info['url']
            title = info.get('title', 'Unknown')

        source = discord.FFmpegPCMAudio(url2, **{'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'})
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop))

        await ctx.send(f"🎵 Now playing: **{title}**")
    except Exception as e:
        await ctx.send(f"Error playing: {str(e)[:100]}")
        await play_next(ctx)

@bot.command(name="join")
async def join(ctx):
    if ctx.author.voice is None:
        return await ctx.send("You're not in a voice channel!")
    if ctx.guild.id in voice_clients:
        return await ctx.send("I'm already in VC!")

    try:
        vc = await ctx.author.voice.channel.connect(self_deaf=True)
        voice_clients[ctx.guild.id] = vc
        queues[ctx.guild.id] = []
        await ctx.send(f"Joined {ctx.author.voice.channel.name}! ✨")
        asyncio.create_task(keep_alive(vc))
    except Exception as e:
        await ctx.send(f"Failed to join: {str(e)[:80]}")

async def keep_alive(vc):
    while vc.is_connected():
        try:
            if not vc.is_playing():
                source = discord.FFmpegPCMAudio(io.BytesIO(b'\x00' * 48000), pipe=True)
                vc.play(source)
            await asyncio.sleep(25)
        except:
            break

@bot.command(name="leave")
async def leave(ctx):
    if ctx.guild.id not in voice_clients:
        return await ctx.send("I'm not in a voice channel!")
    try:
        await voice_clients[ctx.guild.id].disconnect()
        voice_clients.pop(ctx.guild.id, None)
        queues.pop(ctx.guild.id, None)
        await ctx.send("Left the voice channel~ 👋")
    except:
        pass

@bot.command(name="play")
async def play(ctx, *, query: str):
    if ctx.guild.id not in voice_clients:
        await join(ctx)

    vc = voice_clients[ctx.guild.id]

    if "youtube.com" in query or "youtu.be" in query:
        url = query
    else:
        with yt_dlp.YoutubeDL({'format': 'bestaudio/best', 'quiet': True, 'default_search': 'ytsearch', 'nocheckcertificate': True}) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
            url = info['webpage_url']

    queues.setdefault(ctx.guild.id, []).append(url)

    if not vc.is_playing():
        await play_next(ctx)
    else:
        await ctx.send("Added to queue!")

@bot.command(name="skip")
async def skip(ctx):
    if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_playing():
        voice_clients[ctx.guild.id].stop()
        await ctx.send("Skipped! ⏭️")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name="stop")
async def stop(ctx):
    if ctx.guild.id in voice_clients:
        voice_clients[ctx.guild.id].stop()
        queues[ctx.guild.id] = []
        await ctx.send("Stopped music.")

@bot.command(name="song")
async def song_command(ctx, *, country: str = None):
    if not country: return await ctx.send("Which country?")
    answer = await get_accurate_grok_answer(f"Current most popular song in {country}")
    await ctx.send(f"**🎵 Top song in {country}:** {answer}")

@bot.command(name="singer")
async def singer_command(ctx, *, country: str = None):
    if not country: return await ctx.send("Which country?")
    answer = await get_accurate_grok_answer(f"Most popular singer in {country}")
    await ctx.send(f"**🎤 Top singer in {country}:** {answer}")

async def get_accurate_grok_answer(question: str):
    def _search():
        try:
            resp = sync_client.chat.completions.create(
                model="grok-4",
                messages=[{"role": "user", "content": f"Answer this accurately: {question}"}],
                max_tokens=200
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"Web search error: {e}")
            return "Couldn't fetch right now."
    return await asyncio.to_thread(_search)

@bot.event
async def on_ready():
    print(f"✅ AstraMizu is online as {bot.user} | Ready!")

bot.run(os.getenv("DISCORD_TOKEN"))