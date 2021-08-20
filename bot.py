import discord
from models import db, Webhook as DBWebhook, TelegramChannel, Watchgroup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import yaml
from discord_slash import SlashCommand
from discord_slash.utils.manage_commands import create_option


dclient = discord.Client()
dcslash = SlashCommand(dclient, sync_commands=True)

config = yaml.safe_load(open('config.yml'))

sqlengine = create_engine(config['dburl'])
sqlsessionmaker = sessionmaker(bind=sqlengine)

@dcslash.subcommand(base="webhook",
               name="create",
               description="Add a webhook to the news feed.",
               options=[
                   create_option(
                       name="url",
                       description="Webhook URL",
                       option_type=3,
                       required=True
                   )
               ],
               guild_ids=[***REMOVED***])
async def _addwh(ctx, url: str):
    session = sqlsessionmaker()
    wh = DBWebhook(url=url, serverid=ctx.guild.id)
    session.add(wh)
    session.commit()

    await ctx.send("ok", hidden=True)

@dcslash.subcommand(base="watchgroup",
               name="create",
               description="Create a Watchgroup.",
               options=[
                   create_option(
                       name="name",
                       description="Watchgroup Name",
                       option_type=3,
                       required=True
                   )
               ],
               guild_ids=[***REMOVED***])
async def _addwg(ctx, name):
    session = sqlsessionmaker()
    wg = Watchgroup(name=name)
    session.add(wg)
    session.commit()

    await ctx.send("ok", hidden=True)

@dcslash.subcommand(base="channel",
               name="list",
               description="List all Telegram channels.",
               guild_ids=[***REMOVED***])
async def _listtgc(ctx):
    session = sqlsessionmaker()
    channels = session.query(TelegramChannel).all()
    if len(channels) > 0:
        pp = ""
        for channel in channels:
            pp += f'({channel.id}) {channel.name} - {channel.id}\n'
        else:
            await ctx.send(pp, hidden=True)
    else:
        await ctx.send("There are no Telegram channels to list.", hidden=True)

@dcslash.subcommand(base="watchgroup",
               name="list",
               description="List all Watchgroups.",
               guild_ids=[***REMOVED***])
async def _listwg(ctx):
    session = sqlsessionmaker()
    watchgroups = session.query(Watchgroup).all()
    if len(watchgroups) > 0:
        pp = ""
        for watchgroup in watchgroups:
            pp += f'({watchgroup.id}) {watchgroup.name} - {len(watchgroup.channels)} channels\n'
        else:
            await ctx.send(pp, hidden=True)
    else:
        await ctx.send("There are no watchgroups to list.", hidden=True)

@dcslash.subcommand(base="webhook",
               name="listwebhooks",
               description="List all Discord webhooks.",
               guild_ids=[***REMOVED***])
async def _listwh(ctx):
    session = sqlsessionmaker()
    webhooks = session.query(DBWebhook).all()
    if len(webhooks) > 0:
        pp = ""
        for webhook in webhooks:
            pp += f'({webhook.id}) {webhook.url} - {len(webhook.watched)} explicitly watched channels, {len(webhook.watchgroups)} watched watchgroups\n'
        else:
            await ctx.send(pp, hidden=True)
    else:
        await ctx.send("There are no webhooks to list.", hidden=True)

@dcslash.subcommand(base="webhook",
               subcommand_group="add",
               name="watchgroup",
               description="Add a Watchgroup to a Discord webhook.",
               options=[
                   create_option(
                       name="wgid",
                       description="Watchgroup ID",
                       option_type=4,
                       required=True
                   ),
                   create_option(
                       name="whid",
                       description="Webhook ID",
                       option_type=4,
                       required=True
                    )
               ],
               guild_ids=[***REMOVED***])
async def _addtgctowg(ctx, wgid, whid):
    session = sqlsessionmaker()
    wh = session.query(DBWebhook).filter(DBWebhook.id == whid).one()
    wg = session.query(Watchgroup).filter(Watchgroup.id == wgid).one()
    wh.watchgroups.append(wg)
    session.commit()

    await ctx.send("ok", hidden=True)

@dcslash.subcommand(base="webhook",
               subcommand_group="add",
               name="channel",
               description="Add a Telegram channel to a Discord webhook.",
               options=[
                   create_option(
                       name="tgcid",
                       description="Telegram Channel ID",
                       option_type=4,
                       required=True
                   ),
                   create_option(
                       name="whid",
                       description="Webhook ID",
                       option_type=4,
                       required=True
                   )
               ],
               guild_ids=[***REMOVED***])
async def _addtgctowh(ctx, tgcid, whid):
    session = sqlsessionmaker()
    wh = session.query(DBWebhook).filter(DBWebhook.id == whid).one()
    tgc = session.query(TelegramChannel).filter(TelegramChannel.id == tgcid).one()
    wh.watched.append(tgc)
    session.commit()

    await ctx.send("ok", hidden=True)

@dcslash.subcommand(base="watchgroup",
               subcommand_group="add",
               name="channel",
               description="Add a Telegram channel to a Watchgroup.",
               options=[
                  create_option(
                      name="tgcid",
                      description="Telegram Channel ID",
                      option_type=4,
                      required=True
                  ),
                  create_option(
                      name="wgid",
                      description="Watchgroup ID",
                      option_type=4,
                      required=True
                  )
               ],
               guild_ids=[***REMOVED***])
async def _addtgctowg(ctx, tgcid, wgid):
    session = sqlsessionmaker()
    wg = session.query(Watchgroup).filter(Watchgroup.id == wgid).one()
    tgc = session.query(TelegramChannel).filter(TelegramChannel.id == tgcid).one()
    wg.channels.append(tgc)
    session.commit()

    await ctx.send("ok", hidden=True)


@dcslash.subcommand(base="channel",
               name="register",
               description="Register a Telegram channel for use by the news feed.",
               options=[
                   create_option(
                       name="tgcid",
                       description="Telegram Channel ID",
                       option_type=4,
                       required=True
                   )
               ],
               guild_ids=[***REMOVED***])
async def registertg(ctx, tgcid):
    session = sqlsessionmaker()
    tgc = session.query(TelegramChannel).filter(TelegramChannel.id == tgcid).one()
    tgc.registered = True
    session.commit()
    await ctx.send("ok", hidden=True)