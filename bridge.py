import asyncio
# from telethon import TelegramClient, events
# import telethon
import pyrogram
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
import mimetypes

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

tgclient = pyrogram.Client(config['telegram']['sessionfile'], config['telegram']['api_id'], config['telegram']['api_hash'])

def is_watched(message):
    session = sqlsessionmaker()

    try:
        channel = session.query(TelegramChannel).filter(TelegramChannel.id == int(message.chat.id)).one()
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

    session.close()
    return outhooks

# TODO: better path handling with pathlib
@tgclient.on_message()
async def on_message(client, message):
    if message.sender_chat == 777000 or message.chat == 777000:
        return # don't send anything from official telegram system channel either

    whurls = [webhook.url for webhook in is_watched(message)] # get webhooks that are interested in this message

    for webhook in whurls:
        async with aiohttp.ClientSession() as session:
            fwname = ''
            webhookmsg = ''

            # chat icon handling
            ifp = f"{message.chat.id}.jpg"  # Channel icons can be assumed to be JPEGs for the foreseeable future.
            if message.chat.photo and not os.path.exists(config['telegram']['files_dir'] + ifp):
                await tgclient.download_media(message.chat.photo.small_file_id, file_name=config['telegram']['files_dir'] + ifp)

            # forward handling
            try:
                if message.forward_from: # forwarded from user
                    fwname = f'Forwarded from {message.forward_from.first_name} {message.forward_from.last_name} (@{message.forward_from.username})'

                elif message.forward_from_chat: # forwarded from chat
                    if message.forward_from_chat.title:
                        fwname = f"Forwarded from {message.forward_from_chat.title}"
                    else:
                        # WARN: may or may not work for chats
                        fwname = f'Forwarded from {message.forward_from_chat.first_name} {message.forward_from_chat.last_name}'

                elif message.forward_sender_name:  # forwarded from hidden account's comment
                    fwname = f'Forwarded from {message.forward_sender_name} (Hidden Account)'
            except:
                fwname = "**An exception has occurred fetching the origin channel.**"

            if fwname != None:
                webhookmsg += f"{fwname}\n\n"
            if message.text != None:
                webhookmsg += f"{message.text}"
            elif message.caption != None:
                webhookmsg += f"{message.caption}"

            # file download handling
            # message.media tells us the type of media to get attributes of
            if message.media and message.media != "web_page":
                filename = f"{message.chat.id}-{message.message_id}{mimetypes.guess_extension(message[message.media].mime_type)}"
                # equates to something like files/-1001427017788-357.mp4
                await message.download(file_name=config['telegram']['files_dir']+filename)

                webhookmsg += f'\n\n{config["telegram"]["base_url"]}{filename}'

            # final webhook request handling
            username = message.chat.title if message.chat.title else f'{message.chat.first_name} {message.chat.last_name}'
            webhook = Webhook.from_url(webhook, adapter=AsyncWebhookAdapter(session))
            await webhook.send(webhookmsg, username=message.chat.title, avatar_url=config['telegram']['base_url']+ifp)


async def main():
    session = sqlsessionmaker()

    await tgclient.start()  # start Pyrogram client

    # TODO: change names of channels if they dont match since previous start
    # TODO: listen for channel leaves/joins/renames and react accordingly
    async for dialog in tgclient.iter_dialogs():
        chname = dialog.chat.title if dialog.chat.title else f'{dialog.chat.first_name} {dialog.chat.last_name}'

        if session.query(TelegramChannel).filter(TelegramChannel.id == dialog.chat.id).count() == 0:
            if int(dialog.chat.id) == 777000:  # do not add the Telegram system channel to the database at all
                continue

            channel = TelegramChannel(id=dialog.chat.id, name=chname, registered=False)
            session.add(channel)
            session.commit()
            print(f'{channel.name} ({channel.id} was added to the database.')
        else:
            channel = session.query(TelegramChannel).filter(TelegramChannel.id == dialog.chat.id).one()
            if channel.name != chname:
                channel.name = chname
                print(f'Channel {chname} was renamed on Telegram, renaming to {channel.name} in database.')
                session.add(channel)
                session.commit()
    else:
        session.close()

    await pyrogram.idle() # idle until told to stop
    print("stopping")

    # we have received a signal to stop
    await tgclient.stop()
    

# dbot = loop.create_task(dclient.start("***REMOVED***", bot=True))
tgbot = loop.create_task(main())
# cli = loop.create_task(climain())
gathered = asyncio.gather(tgbot)

loop.run_until_complete(gathered)
