import asyncio
from telethon import TelegramClient, events
from prompt_toolkit.patch_stdout import patch_stdout
import telethon
from discord import Webhook, AsyncWebhookAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from console import climain
import yaml
import aiohttp
import os
import logging
import sqlalchemy.exc
from rich.logging import RichHandler

# noinspection PyArgumentList
logging.basicConfig(format='%(message)s', datefmt="[%X]", level=logging.WARNING, handlers=[RichHandler()])
logger = logging.getLogger('bridge')
logger.setLevel(logging.DEBUG)

config = yaml.safe_load(open('config.yml'))

sqlengine = create_engine(config['dburl'])
sqlsessionmaker = sessionmaker(bind=sqlengine)

from models import db, Webhook as DBWebhook, TelegramChannel, Watchgroup
# db.metadata.drop_all(sqlengine)
db.metadata.create_all(sqlengine)

#config['telegram']['base_url'] = "https://ccrda.us/tgbridge/" # TODO: handle trailing slash
#config['telegram']['files_dir'] = "files/" # TODO: handle trailing slash

loop = asyncio.get_event_loop()

# The first parameter is the .session file name (absolute paths allowed)
tgclient = TelegramClient(config['telegram']['sessionfile'], config['telegram']['api_id'], config['telegram']['api_hash'], loop=loop)
# from bot import dclient

def is_watched(event):
    session = sqlsessionmaker()

    try:
        channel = session.query(TelegramChannel).filter(TelegramChannel.id == int(event.chat_id)).one()
    except sqlalchemy.exc.NoResultFound:
        return []

    if not channel.registered:
        logger.debug(f'{channel.name} ({channel.id}) is not registered')
        return []  # return an empty list instead of None so list comprehension doesn't fail

    outhooks = []

    # Get webhooks which explicitly watch this channel.
    outhooks += session.query(DBWebhook).filter(DBWebhook.watched.any(id=channel.id)).all()

    # Get webhooks which watch this channel by watchgroup.
    outhooks += session.query(DBWebhook).join(Watchgroup, DBWebhook.watchgroups).filter(Watchgroup.channels.any(id=channel.id)).all()

    outhooks = list(set(outhooks))  # De-duplicate webhooks list.

    return outhooks

@tgclient.on(events.NewMessage())
async def on_message(event):
    whurls = [webhook.url for webhook in is_watched(event)]

    for webhook in whurls:
        async with aiohttp.ClientSession() as session:
            webhookmsg = ''
            chat = await event.get_chat()

            ifp = f"{event.chat_id}.jpg"  # Channel icons can be assumed to be JPEGs for the foreseeable future.
            if not os.path.exists(ifp) and not isinstance(chat.photo, telethon.types.ChatPhotoEmpty):
                await tgclient.download_profile_photo(await event.get_chat(), file=config['telegram']['files_dir'] + ifp)

            if event.message.forward:
                try:
                    if event.message.forward.from_id:
                        ent = await tgclient.get_entity(event.message.forward.from_id)
                        if isinstance(ent, telethon.types.User):
                            name = f'{ent.first_name} {ent.last_name}'
                        else:
                            name = f'{ent.title}'
                    else:
                        name = f'{event.message.forward.from_name}'

                    webhookmsg += f'Forwarded from {name}\n\n'
                except:
                    name = "**An exception has occurred fetching the origin channel.**"

            webhookmsg += f"{event.message.message}"

            if event.message.file and not event.message.web_preview:
                if event.message.file.ext == ".jpe":
                    mfpext = ".jpg"
                else:
                    mfpext = event.message.file.ext

                mfp = f'{event.chat_id}-{event.message.id}{mfpext}'

                with open(config['telegram']['files_dir']+mfp, 'wb') as f:
                    async for chunk in tgclient.iter_download(event.message.file.media):
                        f.write(chunk)

                webhookmsg += f'\n\n{config["telegram"]["base_url"]}{mfp}'

            webhook = Webhook.from_url(webhook, adapter=AsyncWebhookAdapter(session))
            # coroutine to get self is in parenthesis so .id runs on the result of awaiting it
            if not isinstance(chat, telethon.types.User):
                await webhook.send(webhookmsg, username=f'{chat.title}', avatar_url=config['telegram']['base_url']+ifp)
            elif (await tgclient.get_me()).id == event.chat_id:
                await webhook.send(webhookmsg, username=f'Saved Messages', avatar_url=config['telegram']['base_url']+ifp)
            elif isinstance(chat, telethon.types.User):
                await webhook.send(webhookmsg, username=f'DM with {chat.first_name} {chat.last_name}', avatar_url=config['telegram']['base_url']+ifp)


async def main():
    session = sqlsessionmaker()

    await tgclient.start()  # Log into Telegram.

    # TODO: change names of channels if they dont match since previous start
    # TODO: listen for channel leaves/joins/renames and react accordingly
    async for dialog in tgclient.iter_dialogs():
        if session.query(TelegramChannel).filter(TelegramChannel.id == dialog.id).count() == 0:
            channel = TelegramChannel(id=dialog.id, name=dialog.name, registered=False)
            session.add(channel)
            session.commit()
            print(f'{dialog.name} ({dialog.id} was added to the database.')

    await tgclient.run_until_disconnected()  # Keep Telethon bot running.


# dbot = loop.create_task(dclient.start("***REMOVED***", bot=True))
tgbot = loop.create_task(main())
cli = loop.create_task(climain())
gathered = asyncio.gather(tgbot, cli, loop=loop)

loop.run_until_complete(gathered)
