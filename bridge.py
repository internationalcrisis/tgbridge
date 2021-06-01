from telethon import TelegramClient, events
import telethon
from discord import Webhook, AsyncWebhookAdapter
from pprint import pprint

import yaml
import aiohttp
import os
import logging
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.WARNING)

config = yaml.safe_load(open('config.yml'))

# Use your own values from my.telegram.org
api_id = ***REMOVED***
api_hash = '***REMOVED***'

config['telegram']['base_url'] = "https://ccrda.us/tgbridge/" # TODO: handle trailing slash
config['telegram']['files_dir'] = "files/" # TODO: handle trailing slash


loggedchats = [
    ***REMOVED***
    ***REMOVED***
    ***REMOVED***
    ***REMOVED***
    ***REMOVED***
]

# The first parameter is the .session file name (absolute paths allowed)
client = TelegramClient(config['telegram']['sessionfile'], config['telegram']['api_id'], config['telegram']['api_hash'])

@client.on(events.NewMessage(chats=config['telegram']['watched']))
async def on_message(event):
    async with aiohttp.ClientSession() as session:
        webhookmsg = ''

        ifp = f"{event.chat.id}.jpg"
        if not os.path.exists(ifp) and not isinstance(event.chat.photo, telethon.types.ChatPhotoEmpty):
            await client.download_profile_photo(event.chat, file=config['telegram']['files_dir']+ifp)

        if event.message.forward:
            try:
                if event.message.forward.from_id:
                    ent = await client.get_entity(event.message.forward.from_id)
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

            mfp = f'{event.chat.id}-{event.message.id}{mfpext}'

            with open(config['telegram']['files_dir']+mfp, 'wb') as f:
                async for chunk in client.iter_download(event.message.file.media):
                    f.write(chunk)
            
            webhookmsg += f'\n\n{config["telegram"]["base_url"]}{mfp}'

        webhook = Webhook.from_url(config['discord']['webhookurl'], adapter=AsyncWebhookAdapter(session))
        # coroutine to get self is in parenthesis so .id runs on the result of awaiting it
        if not isinstance(event.chat, telethon.types.User):
            await webhook.send(webhookmsg, username=f'{event.chat.title}', avatar_url=config['telegram']['base_url']+ifp)
        elif (await client.get_me()).id == event.chat.id: 
            await webhook.send(webhookmsg, username=f'Saved Messages', avatar_url=config['telegram']['base_url']+ifp)
        elif isinstance(event.chat, telethon.types.User):
            await webhook.send(webhookmsg, username=f'DM with {event.chat.first_name} {event.chat.last_name}', avatar_url=config['telegram']['base_url']+ifp)

async def main():
    async for dialog in client.iter_dialogs():
        print(f'{dialog.name} ({dialog.id})')

    await client.run_until_disconnected()


client.start()
client.loop.run_until_complete(main())
