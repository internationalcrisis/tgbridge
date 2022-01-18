import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from flask import Flask, request
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView

config = yaml.safe_load(open('config.yml'))

sqlengine = create_engine(config['dburl'])
sqlsessionmaker = sessionmaker(bind=sqlengine)

from models import db, Webhook as DBWebhook, TelegramChannel, Watchgroup


class TelegramChannelView(ModelView):
    can_create = False
    can_delete = False
    form_excluded_columns = ["name"]
    column_searchable_list = ["id", 'name']
    column_sortable_list = ["id", "name", "watchgroupcount", "webhookcount", "registered"]
    column_list = ["id", "name", "watchgroupcount", "webhookcount", "registered"]
    column_filters = ['registered']
    column_labels = {
        "id": "Telegram Chat ID",
        "webhookcount": "Webhooks Watching",
        "watchgroupcount": "Watchgroups Watching"
    }
    column_descriptions = {
        "registered": "Whether or not this webhook should be available for usage."
    }


class WatchgroupView(ModelView):
    column_searchable_list = ["id", 'name']
    column_list = ["id", "name", "channelcount", "webhookcount"]
    column_sortable_list = ["id", "name", "channelcount", "webhookcount"]
    column_labels = {
        "id": "UUID",
        "channelcount": "Watched Channels",
        "webhookcount": "Webhooks Watching"
    }

class WebhookView(ModelView):
    column_searchable_list = ["id", 'url']
    column_list = ["id", "url", "watchgroupcount", "channelcount"]
    column_sortable_list = ["id", "url", "watchgroupcount", "channelcount"]
    column_labels = {
        "id": "UUID",
        "url": "Discord Webhook URL",
        "channelcount": "Watched Channels",
        "watchgroupcount": "Watched Watchgroups",
        "serverid": "Discord Guild ID"
    }
    column_descriptions = {
        "url": "The Discord Webhook URL, view details to view full URL."
    }
    column_formatters = {
        "url": lambda v, c, m, p: m.url if "details" in request.path else m.url[:50]+'...' # TODO: find details view better
    }
    can_view_details = True

# db.metadata.drop_all(sqlengine)
db.metadata.create_all(sqlengine)

app = Flask(__name__)
app.config['SECRET_KEY'] = "Amogus"

app.config['FLASK_ADMIN_SWATCH'] = 'slate'

admin = Admin(app, name='tgbridge', template_mode='bootstrap4')
admin.add_view(TelegramChannelView(TelegramChannel, sqlsessionmaker()))
admin.add_view(WatchgroupView(Watchgroup, sqlsessionmaker()))
admin.add_view(WebhookView(DBWebhook, sqlsessionmaker()))

app.run(debug=True, use_reloader=True)
