import asyncio
from telethon import TelegramClient, events
import telethon
from discord import Webhook, AsyncWebhookAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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

from models import db, Webhook as DBWebhook, TelegramChannel, Watchgroup, TelegramMessage, DiscordMessage
# db.metadata.drop_all(sqlengine)
db.metadata.create_all(sqlengine)

tgclient = telethon.TelegramClient(config['telegram']['sessionfile'], config['telegram']['api_id'], config['telegram']['api_hash'])

def is_watched(message):
    session = sqlsessionmaker()

    try:
        channel = session.query(TelegramChannel).filter(TelegramChannel.id == int(message.chat_id)).one()
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

# @tgclient.on_disconnect()
# async def on_disconnect(client):
    # logger.warning("Pyrogram client was disconnected.")

# TODO: better path handling with pathlib
@tgclient.on(events.NewMessage())
async def on_message(event):
    sqlsession = sqlsessionmaker()
    chat = await event.get_chat()

    if event.chat_id == 777000 or event.sender_id == 777000:
        return # don't send anything from official telegram system channel either

    # if no TelegramMessage wxith this message id and channel id exists, create one.
    tmsg = sqlsession.query(TelegramMessage).filter(TelegramMessage.messageid == event.message.id, TelegramMessage.channelid == event.chat_id).one_or_none()
    if tmsg is None:
        tmsg = TelegramMessage(messageid=event.message.id, channelid=event.chat_id)
        sqlsession.add(tmsg)
        sqlsession.commit()
    else:
        # this message MAY have been processed before, but check webhooks anyway
        logger.warning(f"Telegram message with message id {tmsg.messageid} and chat id {tmsg.channelid} has been processed before")

    webhooks = [webhook for webhook in is_watched(event)] # get webhooks that are interested in this message

    for webhook in webhooks:
        async with aiohttp.ClientSession() as session:
            if sqlsession.query(DiscordMessage).filter(DiscordMessage.tgmessageid == tmsg.id, DiscordMessage.webhookid == webhook.id).count() >= 1:
                logger.error(f"Webhook with id {webhook.id} has already sent Telegram message with message id {tmsg.messageid} and channel id {tmsg.channelid}, webhook will be skipped.")
                continue # this has been processed before, skip to next webhook

            fwname = ''
            webhookmsg = ''

            # chat icon handling
            ifp = f"{event.chat_id}.jpg"  # Channel icons can be assumed to be JPEGs for the foreseeable future.
            if not os.path.exists(ifp) and not isinstance(chat.photo, telethon.types.ChatPhotoEmpty):
                await tgclient.download_profile_photo(await event.get_chat(), file=config['telegram']['files_dir'] + ifp)

            # forward handling
            try:
                if event.message.forward and event.message.forward.from_id:
                    ent = await event.message.forward.get_chat()

                    if ent.title:
                        fwname = f'Forwarded from {ent.title}'
                    elif ent.first_name and ent.last_name:
                        fwname = f'Forwarded from {ent.first_name} {ent.last_name or ""} @{ent.username}'
                    else:
                        fwname = "Forwarded from "+str(ent.first_name)
                        fwname += " "+str(ent.last_name) if ent.last_name else "" # formatted last name
                elif event.message.forward and not event.message.forward.from_id:
                    fwname = f'{event.message.forward.from_name} (Hidden Account)'
            except Exception as err:
                fwname = "**An exception has occurred fetching the origin channel.**"
                # send the exception to sentry instead of silently catching it
                sentry_sdk.capture_exception(err)

            if fwname and event.message.message:  # forward AND message
                webhookmsg += f"{fwname}\n\n{event.message.message}"
            elif fwname:  # only forward
                webhookmsg += f"{fwname}"
            elif event.message.message:  # only message
                webhookmsg += f"{event.message.message}"

            # file download handling
            if event.message.file and not event.message.web_preview:
                if event.message.file.ext == ".jpe":
                    mfpext = ".jpg"
                else:
                    mfpext = event.message.file.ext

                filename = f"{event.chat_id}-{event.message.id}{mfpext}"
                # equates to something like files/-1001427017788-357.mp4
                with open(config['telegram']['files_dir']+filename, 'wb') as f:
                    async for chunk in tgclient.iter_download(event.message.file.media):
                        f.write(chunk)


                webhookmsg += f'\n\n{config["telegram"]["base_url"]}{filename}'

            # final webhook request handling
            username = chat.title if chat.title else f'{chat.first_name} {chat.last_name}'
            webhook = Webhook.from_url(webhook.url, adapter=AsyncWebhookAdapter(session))
            if not isinstance(chat, telethon.types.User):
                dmessage = await webhook.send(webhookmsg, username=f'{chat.title}', avatar_url=config['telegram']['base_url']+ifp, wait=True)
            elif (await tgclient.get_me()).id == event.chat_id:
                dmessage = await webhook.send(webhookmsg, username=f'Saved Messages', avatar_url=config['telegram']['base_url']+ifp, wait=True)
            elif isinstance(chat, telethon.types.User):
                dmessage = await webhook.send(webhookmsg, username=f'DM with {chat.first_name} {chat.last_name}', avatar_url=config['telegram']['base_url']+ifp, wait=True)
            else:
                raise Exception("Invalid event type for webhook formatting")

            # log that the telegram message has been sent to this webhook
            dmsg = DiscordMessage(id=dmessage.id, tgmessage=tmsg, webhookid=webhook.id)
            sqlsession.add(dmsg)
            sqlsession.commit()


async def main():
    session = sqlsessionmaker()

    logger.info("Starting Telethon client..")
    await tgclient.start()  # start Telethon client
    logger.info("Telethon client started, checking chats list..")

    # TODO: change names of channels if they dont match since previous start
    # TODO: listen for channel leaves/joins/renames and react accordingly
    async for dialog in tgclient.iter_dialogs():
        chname = ''
        if dialog.title:
            chname = dialog.title
        elif dialog.first_name and dialog.last_name:
            chname = f'{dialog.first_name} {dialog.last_name or ""}'
        else:
            # first name and/or last name is not available
            chname = dialog.first_name
            chname += " "+str(dialog.last_name) if dialog.last_name else "" # formatted last name

        logger.debug(f'Found chat {chname} ({dialog.id})')
        if session.query(TelegramChannel).filter(TelegramChannel.id == dialog.id).count() == 0:
            if int(dialog.id) == 777000:  # do not add the Telegram system channel to the database at all
                continue

            channel = TelegramChannel(id=dialog.id, name=chname, registered=False)
            session.add(channel)
            session.commit()
            logger.info(f'{channel.name} ({channel.id} was added to the database.')
        else:
            channel = session.query(TelegramChannel).filter(TelegramChannel.id == dialog.id).one()
            if channel.name != chname:
                channel.name = chname
                logger.info(f'Channel {chname} was renamed in Telegram, renaming to {channel.name} in database.')
                session.add(channel)
                session.commit()
    else:
        session.close()

    logger.info('Startup tasks were completed, listening for new events..')
    await tgclient.run_until_disconnected() # idle until told to stop
    logger.info("Signal received, exiting gracefully..")

    #we have received a signal to stop
    await tgclient.stop()
    

asyncio.run(main())