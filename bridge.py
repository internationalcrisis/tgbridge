import asyncio
import telethon
from discord import Webhook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import yaml
import aiohttp
import os
import logging
import re
import sqlalchemy.exc
from rich.logging import RichHandler
import shutil
import b2sdk
import sys
from b2sdk.v2 import InMemoryAccountInfo, B2Api
import telethon.events as tgevents

# pylint: disable=missing-class-docstring, missing-function-docstring, invalid-name

# noinspection PyArgumentList
logging.basicConfig(format='%(message)s', datefmt="[%X]", level=logging.WARNING, handlers=[RichHandler()])
logger = logging.getLogger('bridge')
logger.setLevel(logging.DEBUG)

from config import Settings

if os.environ.get("TGBRIDGE_ENVCONFIG"):
    settings = Settings()  # Exclusively use environment variables for configuration.
elif os.path.exists(os.environ.get('CONFIG', "config.yml")):
    config = yaml.safe_load(open(os.environ.get('CONFIG', "config.yml")))
    settings = Settings.parse_obj(config)
else:
    logger.warning(f"No config file was found at {os.environ.get('CONFIG', 'config.yml')}, failing over to environment variables.\nIf this was intentional, set TGBRIDGE_ENVCONFIG=true to hide this warning.")
    settings = Settings()

sqlengine = create_engine(settings.dburl)
sqlsessionmaker = sessionmaker(bind=sqlengine)

from models import db, Webhook as DBWebhook, TelegramChannel, Watchgroup, TelegramMessage, DiscordMessage
# db.metadata.drop_all(sqlengine)
db.metadata.create_all(sqlengine)


def slash_join(*args):
    '''
    Joins a set of strings with a slash (/) between them. Useful for creating URLs.
    If the strings already have a trailing or leading slash, it is ignored.
    Note that the python's urllib.parse.urljoin() does not offer this functionality.

    https://codereview.stackexchange.com/questions/175421/joining-strings-to-form-a-url
    '''
    return "/".join(arg.strip("/") for arg in args)

async def upload_media(filename):
    """Upload file named `filename` which is in the configured cache directory to configured storage, then delete the cached copy after upload."""
    if settings.storage.local.enabled:
        shutil.copyfile(settings.storage.cache_dir+filename, slash_join(settings.storage.local.file_prefix, filename))

        try:
            os.remove(settings.storage.cache_dir+filename)
        except FileNotFoundError:
            pass # If it doesn't exist, we don't need to do anything about it.

        # {url_prefix}/{filename}
        url = slash_join(settings.storage.local.url_prefix, filename)
        logger.debug(f'URL created using local storage: {url}')
        return url

    elif settings.storage.b2.enabled:
        info = InMemoryAccountInfo()  # TODO: put this somewhere else
        b2_api = B2Api(info)
        b2_api.authorize_account("production", settings.storage.b2.api_id, settings.storage.b2.api_key)

        if settings.storage.b2.bucket_name:
            bucket = b2_api.get_bucket_by_name(settings.storage.b2.bucket_name)
        elif settings.storage.b2.bucket_id:
            bucket = b2_api.get_bucket_by_id(settings.storage.b2.bucket_id)
        else:
            raise Exception("no bucket name or id given")

        try:
            bucket.get_file_info_by_name(slash_join(settings.storage.b2.file_prefix, filename))
        except b2sdk.exception.FileNotPresent:
            bucket.upload_local_file(
                local_file=os.path.join(settings.storage.cache_dir, filename),
                file_name=slash_join(settings.storage.b2.file_prefix, filename)
            )
        else:
            logger.debug(f"File \"{os.path.join(settings.storage.b2.file_prefix, filename)}\" already exists on B2 Backblaze.")

        try:
            os.remove(os.path.join(settings.storage.cache_dir, filename))
        except FileNotFoundError:
            pass # If it doesn't exist, we don't need to do anything about it.

        # {url_prefix}/file/{bucket.name}/{url_prefix}{filename}
        url = slash_join(settings.storage.b2.url_prefix, "/file/"+bucket.name, settings.storage.b2.file_prefix, filename)

        logger.debug(f'URL created using B2 Backblaze storage: {url}')
        return url

# TODO: a flag to allow/deny large files beyond a certain size?
# FIXME: replace dictionary subscripting with .get and/or validation so its actually reliable
async def download_media_message(tgclient, message):
    if message.file and not message.web_preview:
        # These are all JPEGs, renaming them makes it easier for everyone.
        # .jpe is the only one seen on Telegram due to a Telegram quirk though.
        if message.file.ext in [".jpe", ".jpeg", ".jfif"]:
            mfpext = ".jpg"
        else:
            mfpext = message.file.ext

        filename = f"{message.chat_id}-{message.id}{mfpext}"
        # download the file to cached directory so we can pass it to other handlers
        with open(os.path.join(settings.storage.cache_dir, filename), 'wb') as f:
            async for chunk in tgclient.iter_download(message.file.media):
                f.write(chunk)

        return await upload_media(filename)

# TODO: hash db to see if we've downloaded a profile photo before
async def download_profile_photo(event):
    """Download a Chat's profile photo from an event (preferably NewMessage) and upload it for use from the configured storage system."""
    chat = await event.get_chat()
    tgclient = event.client

    filename = f"{event.chat_id}.jpg"  # Channel icons can be assumed to be JPEGs for the foreseeable future.
    if not os.path.exists(filename) and not isinstance(chat.photo, telethon.types.ChatPhotoEmpty):
        await tgclient.download_profile_photo(await event.get_chat(), file=os.path.join(settings.storage.cache_dir, filename))
        return await upload_media(filename)
    else:
        return None


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

async def format_forwarding(event):
    if event.forward:
        # Accounts which hide their account link in forwards will have a name but no ID.
        if event.forward.from_name and not event.forward.from_id:
            return f'{event.forward.from_name} (Hidden Account)'
        # Accounts that allow passing their account link in forwards will have an attached PeerUser.
        # In this context, the username is the account link.
        elif isinstance(event.forward.from_id, telethon.types.PeerUser):
            ent = await event.forward.get_sender()
            fwname = "Forwarded from"

            if ent.first_name:
                fwname += " "+ent.first_name
            if ent.last_name:
                fwname += " "+ent.last_name
            if ent.username:
                fwname += " @"+ent.username

            return fwname
        # Channels will have an attached ID.
        elif isinstance(event.forward.from_id, telethon.types.PeerChannel):
            ent = await event.forward.get_chat()
            # The channel has a channel link (public)
            # In this context, the username is the channel link.
            if ent.username:
                if event.forward.post_author:
                    # The channel will show the author of the message instead of only the channel name.
                    return f'Forwarded from [{ent.title}](<https://t.me/{ent.username}> "Join this channel on Telegram") ({event.forward.post_author})'
                else:
                    return f'Forwarded from [{ent.title}](<https://t.me/{ent.username}> "Join this channel on Telegram")'
            else:
                # The channel has no link (private)
                return f'Forwarded from {ent.title} (Private Channel)'


# TODO: Might have an option to disable URL previews because most people who use Telegram
# are used to not having them and will do it themselves
# which may conflict with having URL previews
async def format_message(message):
    text = message.message
    if message.entities:
        for entity in message.entities:
            # Telegram uses UTF-16 codepoint pairs so we can't just slice it.
            # Massive thanks to python-telegram-bot for having information about this.
            if sys.maxunicode == 0xFFFF:
                entity_text = message.raw_text[entity.offset : entity.offset + entity.length]

            entity_text = message.raw_text.encode("utf-16-le")
            entity_text = entity_text[entity.offset * 2 : (entity.offset + entity.length) * 2]
            entity_text = entity_text.decode("utf-16-le")

            # "https://example.com" creates these. Telegram will automatically add "https://" to URLs without a scheme.
            if isinstance(entity, telethon.types.MessageEntityUrl):
                if "://" not in text:  # Don't add https:// if it's already there
                    text = text.replace(entity_text, "https://"+entity_text)

            # Special hyperlinks, Ctrl-K creates these on Telegram desktop.
            elif isinstance(entity, telethon.types.MessageEntityTextUrl):
                text = text.replace(entity_text, f"[{entity_text}]({entity.url})")

            # "@username" creates these.
            elif isinstance(entity, telethon.types.MessageEntityMention):
                text = text.replace(entity_text, f"[{entity_text}](https://t.me/{entity_text})")

            # Don't know what creates these, mentioning user who doesn't have username?
            elif isinstance(entity, telethon.types.MessageEntityMentionName):
                text = text.replace(entity_text, f"[{entity_text}](https://t.me/{entity.user_id})")

            # "``` ```" creates these. Standard Markdown code block.
            elif isinstance(entity, telethon.types.MessageEntityPre):
                text = text.replace(entity_text, f"```{entity.language}\n{entity_text}```")

            # These exist for making sure that the Telegram markdown syntax is translated to Discord's syntax,
            # and are self-explanatory as a result.
            elif isinstance(entity, telethon.types.MessageEntityBold):
                text = text.replace(entity_text, f"**{entity_text}**")
            elif isinstance(entity, telethon.types.MessageEntityItalic):
                text = text.replace(entity_text, f"*{entity_text}*")
            elif isinstance(entity, telethon.types.MessageEntityCode):
                text = text.replace(entity_text, f"`{entity_text}`")
            elif isinstance(entity, telethon.types.MessageEntityStrike):
                text = text.replace(entity_text, f"~~{entity_text}~~")
            elif isinstance(entity, telethon.types.MessageEntityUnderline):  # parsed as --text-- on telegram
                text = text.replace(entity_text, f"__{entity_text}__")

            # # username@domain.tld syntax creates these, but they are not supported on Discord.
            # elif isinstance(entity, telethon.types.MessageEntityEmail):
            #     text = text.replace(entity_text, f"[{entity_text}](mailto:{entity_text})")
            else:
                logger.warn(f'Invalid MessageEntity type {type(entity)}: {entity_text}')

    return text

@tgevents.register(tgevents.Album())
async def on_album(event):
    sqlsession = sqlsessionmaker()
    chat = await event.get_chat()
    tgclient = event.client

    ifp = await download_profile_photo(event)

    webhooks = [webhook for webhook in is_watched(event)] # get webhooks that are interested in this message

    for webhook in webhooks:
        async with aiohttp.ClientSession() as session:

            # forward handling
            try:
                fwname = await format_forwarding(event)
            except:
                fwname = "**An exception has occurred fetching the origin channel.**"

            # message formatting handling
            # TODO: do better
            for message in event:
                if message.message:
                    content = await format_message(message)

            # file download handling
            # TODO: if there are more than 5 links (album or not) then not all of them will show.
            urls = []
            for message in event:
                if message.file and not message.web_preview:
                    urls.append(await download_media_message(tgclient, message))

            webhookmsg = content

            if fwname:
                webhookmsg = fwname + "\n\n" + webhookmsg

            if urls:
                webhookmsg = webhookmsg + '\n\n' + "\n".join(urls)

            # final webhook request handling
            username = chat.title if chat.title else f'{chat.first_name} {chat.last_name}'
            ent = await event.message.get_chat()
            webhook = Webhook.from_url(webhook.url, session=session)
            if not isinstance(chat, telethon.types.User):
                dmessage = await webhook.send(webhookmsg, username=f'{chat.title}', avatar_url=ifp, wait=True)
            elif (await tgclient.get_me()).id == event.chat_id:
                dmessage = await webhook.send(webhookmsg, username=f'Saved Messages', avatar_url=ifp, wait=True)
            elif isinstance(chat, telethon.types.User):
                dmessage = await webhook.send(webhookmsg, username=f'{chat.first_name} {chat.last_name} @{ent.username}', avatar_url=ifp, wait=True)
            else:
                dmessage = await webhook.send(webhookmsg, username=f'Invalid channel', avatar_url=ifp, wait=True)


@tgevents.register(tgevents.NewMessage())
async def on_message(event):
    sqlsession = sqlsessionmaker()
    chat = await event.get_chat()
    tgclient = event.client

    if event.message.grouped_id:
        return # albums will break

    if event.chat_id == 777000 or event.sender_id == 777000:
        return # don't send anything from official telegram system channel either

    # if no TelegramMessage with this message id and channel id exists, create one.
    tmsg = sqlsession.query(TelegramMessage).filter(TelegramMessage.messageid == event.message.id, TelegramMessage.channelid == event.chat_id).one_or_none()
    if tmsg is None:
        tmsg = TelegramMessage(messageid=event.message.id, channelid=event.chat_id)
        sqlsession.add(tmsg)
        sqlsession.commit()
    else:
        # this message MAY have been processed before, but check webhooks anyway
        logger.warning(f"Telegram message with message id {tmsg.messageid} and chat id {tmsg.channelid} has been processed before")

    webhooks = [webhook for webhook in is_watched(event)] # get webhooks that are interested in this message

    ifp = await download_profile_photo(event)

    for webhook in webhooks:
        async with aiohttp.ClientSession() as session:
            if sqlsession.query(DiscordMessage).filter(DiscordMessage.tgmessageid == tmsg.id, DiscordMessage.webhookid == webhook.id).count() >= 1:
                logger.error(f"Webhook with id {webhook.id} has already sent Telegram message with message id {tmsg.messageid} and channel id {tmsg.channelid}, webhook will be skipped.")
                continue # this has been processed before, skip to next webhook

            fwname = ''
            webhookmsg = ''

            # forward handling
            try:
                fwname = await format_forwarding(event)
            except Exception as err:
                fwname = "**An exception has occurred fetching the origin channel.**"

            # Message entity markdown handling
            content = await format_message(event.message)

            # file download handling
            url = await download_media_message(tgclient, event.message)

            webhookmsg = content

            if fwname:
                webhookmsg = fwname + "\n\n" + webhookmsg

            if url:
                webhookmsg = webhookmsg + '\n\n' + url

            # final webhook request handling
            username = chat.title if chat.title else f'{chat.first_name} {chat.last_name}'
            ent = await event.message.get_chat()
            webhook = Webhook.from_url(webhook.url, session=session)
            if not isinstance(chat, telethon.types.User):
                dmessage = await webhook.send(webhookmsg, username=f'{chat.title}', avatar_url=ifp, wait=True)
            elif (await tgclient.get_me()).id == event.chat_id:
                dmessage = await webhook.send(webhookmsg, username=f'Saved Messages', avatar_url=ifp, wait=True)
            elif isinstance(chat, telethon.types.User):
                dmessage = await webhook.send(webhookmsg, username=f'{chat.first_name} {chat.last_name} @{ent.username}', avatar_url=ifp, wait=True)
            else:
                dmessage = await webhook.send(webhookmsg, username=f'Invalid event type', avatar_url=ifp, wait=True)

            # log that the telegram message has been sent to this webhook
            dmsg = DiscordMessage(id=dmessage.id, tgmessage=tmsg, webhookid=webhook.id)
            sqlsession.add(dmsg)
            sqlsession.commit()


async def main():
    # dev rant:
    # so if we use .start(), it'll deadlock during login and won't properly start event handlers
    # but if we use async with (which runs .start or equivalent) it does work
    # what the hell
    logger.info("Starting Telethon client..")
    async with telethon.TelegramClient(settings.telegram.sessionfile, settings.telegram.api_id, settings.telegram.api_hash) as tgclient:
        session = sqlsessionmaker()

        tgclient.add_event_handler(on_album)
        tgclient.add_event_handler(on_message)

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


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise