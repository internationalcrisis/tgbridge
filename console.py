from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.table import Table
from rich import box
from models import Webhook as DBWebhook, TelegramChannel, Watchgroup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from inspect import cleandoc
import yaml
import aiohttp
import asyncio
import telethon

# pylint: disable=missing-class-docstring, missing-function-docstring, invalid-name

config = yaml.safe_load(open('config.yml', mode="r"))

sqlengine = create_engine(config['dburl'])
sqlsessionmaker = sessionmaker(bind=sqlengine)

def resolve(console, objects):
    session = sqlsessionmaker()

    out = []
    for object in objects:
        try:
            out += session.query(TelegramChannel).filter(TelegramChannel.id == int(object)).all()
        except ValueError:
            pass

        out += session.query(DBWebhook).filter(DBWebhook.id == object).all()
        out += session.query(Watchgroup).filter(Watchgroup.id == object).all()

    else:
        table = Table("Type", "ID", box=box.SIMPLE, show_header=True, show_edge=True)

        if len(out) > 0:
            for object in out:
                if isinstance(object, DBWebhook):
                    objtype = "Webhook"
                elif isinstance(object, Watchgroup):
                    objtype = "Watchgroup"
                elif isinstance(object, TelegramChannel):
                    objtype = "Telegram Channel"
                else:
                    objtype = "Unknown"

                table.add_row(str(objtype), str(object.id))
            else:
                console.print(table)
        else:
            print("No results found.")

def info(console, object):
    session = sqlsessionmaker()

    # TODO: optimize for one query if possible
    if session.query(DBWebhook).filter(DBWebhook.id == object).count() > 0:
        object = session.query(DBWebhook).filter(DBWebhook.id == object).one_or_none()

        print(f'Webhook {object.id}')
        print(f'URL: {object.url}')
        print(f'Managed by: {object.serverid}\n')

        session.refresh(object)

        table = Table("ID", "Name", "Registered?", title="Watched Channels", box=box.SIMPLE, show_header=True, show_edge=True)
        if len(object.watched) > 0:
            for channel in object.watched:
                table.add_row(str(channel.id), channel.name, str(channel.registered))
            else:
                console.print(table)
        else:
            print("This webhook has no watched channels.")

        session.refresh(object)

        table = Table("ID", "Name", title="Watched Watchgroups", box=box.SIMPLE, show_header=True, show_edge=True)
        if len(object.watchgroups) > 0:
            for channel in object.watchgroups:
                table.add_row(str(channel.id), channel.name)
            else:
                console.print(table)
        else:
            print("This webhook has no watched watchgroups.")

    elif session.query(Watchgroup).filter(Watchgroup.id == object).count():
        object = session.query(Watchgroup).filter(Watchgroup.id == object).one_or_none()

        print(f'Watchgroup {object.id}')
        print(f'Name: {object.name}')

        session.refresh(object)

        table = Table("ID", "Name", "Registered?", title="Watched Channels", box=box.SIMPLE, show_header=True, show_edge=True)
        if len(object.channels) > 0:
            for channel in object.channels:
                table.add_row(str(channel.id), channel.name, str(channel.registered))
            else:
                console.print(table)
        else:
            print("This watchgroup has no watched channels.")

    elif session.query(TelegramChannel).filter(TelegramChannel.id == object).count():
        object = session.query(TelegramChannel).filter(TelegramChannel.id == object).one_or_none()

        print(f'Telegram Channel {object.id}')
        print(f'Name: {object.name}')
        print(f'Registered? {object.registered}')

        # print(f'Watched by {len(object.webhooks)} webhooks.')
    else:
        print("Unable to find any valid object with the given object id.")

def remove(console, source, objects):
    session = sqlsessionmaker()

    # TODO: optimize for one query if possible
    if session.query(DBWebhook).filter(DBWebhook.id == source).count() > 0:
        source = session.query(DBWebhook).filter(DBWebhook.id == source).one_or_none()
    elif session.query(Watchgroup).filter(Watchgroup.id == source).count():
        source = session.query(Watchgroup).filter(Watchgroup.id == source).one_or_none()
    elif session.query(TelegramChannel).filter(TelegramChannel.id == object).count():
        print("Telegram channels cannot have objects removed from them.")
        return
    else:
        print("Unable to find any valid object with the given target object id.")
        return

    watchgroups = []
    channels = []
    dupcounter = 0
    for value in objects:
        watchgroups += session.query(Watchgroup).filter(Watchgroup.id == value).all()
        try:
            channels += session.query(TelegramChannel).filter(TelegramChannel.id == int(value)).all()
        except ValueError:
            pass

    # TODO: DONT add if already in list instead of only incrementing dupcounter
    if isinstance(source, DBWebhook):
        for watchgroup in watchgroups:
            if watchgroup not in source.watchgroups:
                dupcounter += 1
            else:
                source.watchgroups.remove(watchgroup)
        for channel in channels:
            if channel not in source.watched:
                dupcounter += 1
            else:
                source.watched.remove(channel)

        session.add(source)
        session.commit()
    elif isinstance(source, Watchgroup):
        for channel in channels:
            if channel not in source.channels:
                dupcounter += 1
            else:
                source.channels.remove(channel)

        session.add(source)
        session.commit()
        if len(watchgroups):
            print('Watchgroups cannot be removed from other watchgroups, because they cannot watch other watchgroups.')
        # raise NotImplementedError("Adding to a Watchgroup is not implemented.")

    if dupcounter:
        print(f'Removed {len(watchgroups) + len(channels) - dupcounter} objects ({dupcounter} objects were not removed because they aren\'t watched)')
    else:
        print(f'Removed {len(watchgroups) + len(channels)} objects')

def add(console, source, objects):
    session = sqlsessionmaker()

    # TODO: optimize for one query if possible
    if session.query(DBWebhook).filter(DBWebhook.id == source).count() > 0:
        source = session.query(DBWebhook).filter(DBWebhook.id == source).one_or_none()
    elif session.query(Watchgroup).filter(Watchgroup.id == source).count():
        source = session.query(Watchgroup).filter(Watchgroup.id == source).one_or_none()
    elif session.query(TelegramChannel).filter(TelegramChannel.id == object).count():
        print("Telegram channels cannot have objects added to them.")
        return
    else:
        print("Unable to find any valid object with the given target object id.")
        return

    watchgroups = []
    channels = []
    dupcounter = 0
    for value in objects:
        watchgroups += session.query(Watchgroup).filter(Watchgroup.id == value).all()
        try:
            channels += session.query(TelegramChannel).filter(TelegramChannel.id == int(value)).all()
        except ValueError:
            pass

    # TODO: DONT add if already in list instead of only incrementing dupcounter
    if isinstance(source, DBWebhook):
        for watchgroup in watchgroups:
            if watchgroup in source.watchgroups:
                dupcounter += 1
            source.watchgroups.append(watchgroup)
        for channel in channels:
            if channel in source.watched:
                dupcounter += 1
            source.watched.append(channel)

        session.add(source)
        session.commit()
    elif isinstance(source, Watchgroup):
        for channel in channels:
            if channel in source.channels:
                dupcounter += 1
            source.channels.append(channel)

        session.add(source)
        session.commit()
        if len(watchgroups):
            print('Watchgroups cannot be added to other watchgroups.')
        # raise NotImplementedError("Adding to a Watchgroup is not implemented.")

    if dupcounter:
        print(f'Added {len(watchgroups) + len(channels) - dupcounter} objects ({dupcounter} objects were not added because they were already added)')
    else:
        print(f'Added {len(watchgroups) + len(channels)} objects')

async def climain():
    clisession = PromptSession()
    session = sqlsessionmaker()
    console = Console()

    # TODO: retry on exception
    # TODO: put try except IN the while loop
    try:
        while True:
            with patch_stdout():
                result = await clisession.prompt_async('~ > ')
                result = result.strip().split(" ")

                if result[0] == "help":
                    console.print(cleandoc("""
                        Telegram Bridge Commands

                        info <object>                                    - Retrieve more detailed information on an object.
                        add <target> <object> <object> ...               - Add objects to target.
                        remove <target> <object> <object> ...            - Remove objects from target.
                        clearwh <target>                                 - Remove all watched channels and watchgroups from target webhook[bold red], used for testing.[/bold red]
                        createwebhook <url>                              - Create a Discord Webhook
                        createwg <name>                                  - Create a Watchgroup
                        deletewebhook <id>                               - Delete a Discord Webhook
                        deletewg <id>                                    - Delete a Watchgroup
                        listtgc                                          - List all Telegram channels
                        listwg                                           - List all Watchgroups
                        listwh                                           - List all Discord Webhooks
                        [strike]addtgctowg <telegram channel id> <watchgroup id>[/strike] - [strike]Add a Telegram channel to a Watchgroup[/strike]
                        [strike]addtgctowh <telegram channel id> <webhook id>[/strike]    - [strike]Add a Telegram channel to a Discord Webhook[/strike]
                        [strike]addwgtowh <watchgroup id> <webhook id>[/strike]           - [strike]Add a Watchgroup to a Discord Webhook[/strike]
                        registertg <telegram channel id>                 - Register a Telegram channel for use with the news feed.
                        deregistertg <telegram channel id>               - Revoke a Telegram channel from usage with the news feed.
                    """))

                elif result[0] == "clearwh":
                    source = session.query(DBWebhook).filter(DBWebhook.id == result[1]).one_or_none()
                    if source:
                        source.watched.clear()
                        source.watchgroups.clear()

                        session.add(source)
                        session.commit()
                    else:
                        print('webhook not found')

                elif result[0] == "createwebhook":
                    if result[1].startswith("https://discord.com/api/webhooks/"):
                        async with aiohttp.ClientSession() as aiosession:
                            res = await aiosession.get(url=result[1])
                            if res.status == 200:
                                webhook = await res.json()
                                wh = DBWebhook(url=result[1], serverid=webhook['guild_id'])
                                session.add(wh)
                                session.commit()

                                print(f'created webhook with id {wh.id}')
                            else:
                                print("failed")
                    else:
                        print('invalid')
                elif result[0] == "deletewebhook":
                    object = session.query(DBWebhook).filter(DBWebhook.id == result[1]).one_or_none()

                    if object:
                        session.delete(object)
                        session.commit()
                        print(f"Deleted webhook with id {object.id}")
                
                elif result[0] == "deletewg":
                    object = session.query(Watchgroup).filter(Watchgroup.id == result[1]).one_or_none()

                    if object:
                        session.delete(object)
                        session.commit()
                        print(f"Deleted watchgroup named {object.name} with id {object.id}")

                elif result[0] == "createwg":
                    wg = Watchgroup(name=result[1])
                    session.add(wg)
                    session.commit()

                elif result[0] == 'listtgc':
                    channels = session.query(TelegramChannel).all()
                    table = Table("ID", "Name", "Registered?", box=box.SIMPLE, show_header=True, show_edge=True)

                    if len(channels) > 0:
                        for channel in channels:
                            table.add_row(str(channel.id), channel.name, str(channel.registered))
                        else:
                            console.print(table)
                    else:
                        print("There are no Telegram channels to list.")

                elif result[0] == "listwg":
                    table = Table("ID", "Name", "Watched Channels", box=box.SIMPLE, show_header=True, show_edge=True)

                    watchgroups = session.query(Watchgroup).all()
                    if len(watchgroups) > 0:
                        for watchgroup in watchgroups:
                            table.add_row(str(watchgroup.id), watchgroup.name, str(len(watchgroup.channels)))
                        else:
                            console.print(table)
                    else:
                        print("There are no watchgroups to list.")

                elif result[0] == 'listwh':
                    webhooks = session.query(DBWebhook).all()
                    table = Table("ID", "URL", "Watched Channels", "Watched Watchgroups", box=box.SIMPLE, show_header=True, show_edge=True)

                    # TODO: hide webhook data using regex: https:\/\/discord\.com\/api\/webhooks\/.*
                    if len(webhooks) > 0:
                        for webhook in webhooks:
                            # SQLAlchemy ORM is weird and won't refresh changed children when appended
                            # It WILL refresh the changed children list when it's cleared though
                            # Occam's Razor method is just to session.refresh() it
                            session.refresh(webhook)
                            table.add_row(str(webhook.id), webhook.url[:50], str(len(webhook.watched)), str(len(webhook.watchgroups)))
                        else:
                            console.print(table)
                    else:
                        print("There are no webhooks to list.")

                elif result[0] == "add":
                    try:
                        add(console, result[1], result[2:])
                    except IndexError:
                        print("You need to provide a target object id to manipulate and one or more object ids to start watching.")
                        continue
                    except SystemExit:
                        continue

                elif result[0] == "remove":
                    try:
                        remove(console, result[1], result[2:])
                    except IndexError:
                        print("You need to provide a target object id to manipulate and one or more object ids to stop watching.")
                        continue
                    except SystemExit:
                        continue

                elif result[0] == 'info':
                    try:
                        info(console, result[1])

                    except IndexError:
                        print("You need to provide an object id to retrieve info from.")
                        continue
                    except SystemExit:
                        continue

                elif result[0] == 'resolve':
                    try:
                        resolve(console, result[1:])
                    except SystemExit:
                        continue

                elif result[0] == "registertg":
                    for channel in result[1:]:
                        tgc = session.query(TelegramChannel).filter(TelegramChannel.id == channel).one()
                        if int(tgc.id) == 777000:
                            print("The Telegram channel cannot be registered.")
                            continue
                        tgc.registered = True
                        session.add(tgc)
                        print(f'Registered {tgc.name}')
                    else:
                        session.commit()

                elif result[0] == "deregistertg":
                    for channel in result[1:]:
                        tgc = session.query(TelegramChannel).filter(TelegramChannel.id == channel).one()
                        tgc.registered = False
                        session.add(tgc)
                        print(f'Deregistered {tgc.name}')
                    else:
                        session.commit()

                elif result[0] == "exit":
                    exit(0)

    except (KeyboardInterrupt):
        print("Use exit or Ctrl-D (i.e. EOF) to exit")
        await climain()
    except EOFError:  # Ctrl-D
        exit(0)
    except Exception:
        console.print_exception()
        await climain()

asyncio.run(climain())