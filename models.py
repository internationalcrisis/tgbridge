from sqlalchemy import Column, String, BigInteger, Boolean, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, object_session
from sqlalchemy import text, select, func
from sqlalchemy.ext.hybrid import hybrid_property

db = declarative_base()

# TODO: consider allowing multiple watchgroups per channel
# TODO: consider per-guild user watchgroups

dwh2wg_association_table = Table('dwh2wg_association', db.metadata,
    Column('webhookid', ForeignKey('dwebhook.id'), primary_key=True),
    Column('watchgroupid', ForeignKey('tgwatchgroup.id'), primary_key=True)
)

dwh2tgc_association_table = Table('dwh2tgc_association', db.metadata,
    Column('webhookid', ForeignKey('dwebhook.id'), primary_key=True),
    Column('tgchannelid', ForeignKey('tgchannel.id'), primary_key=True)
)

class Webhook(db):
    __tablename__ = "dwebhook"

    def __repr__(self):
        return f'<Webhook id="{self.id}">'

    # TODO: mandate that webhooks must be added from the same server they were created from
    # TODO: might remove serverid entirely instead
    # TODO: change watched to channels
    id = Column(String(128), primary_key=True, server_default=text("gen_random_uuid()"))
    url = Column(String(128), nullable=False, unique=True)  # The webhook.
    serverid = Column(BigInteger, nullable=False)  # Server that created this webhook.

    watchgroups = relationship("Watchgroup", secondary=dwh2wg_association_table, cascade="all,delete")
    watched = relationship("TelegramChannel", secondary=dwh2tgc_association_table, cascade="all,delete")

    active = Column(Boolean, server_default='1')

    @hybrid_property
    def channelcount(self):
        return object_session(self).query(Webhook).where(Webhook.id == self.id).join(Webhook, TelegramChannel.webhooks).count()

    @channelcount.expression
    def channelcount(self):
        return select([func.count(Webhook.id)]).where(Webhook.id == self.id).join(Webhook, TelegramChannel.webhooks)

    @hybrid_property
    def watchgroupcount(self):
        return object_session(self).query(Webhook).where(Webhook.id == self.id).join(Webhook, Watchgroup.webhooks).count()

    @watchgroupcount.expression
    def watchgroupcount(self):
        return select([func.count(Webhook.id)]).where(Webhook.id == self.id).join(Webhook, Watchgroup.webhooks)

class Watchgroup(db):
    __tablename__ = "tgwatchgroup"

    def __repr__(self):
        return f'<Watchgroup id="{self.id}" name="{self.name}">'

    id = Column(String(128), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(128), unique=True, nullable=False)

    channels = relationship("TelegramChannel", cascade="all,delete")
    webhooks = relationship("Webhook", secondary=dwh2wg_association_table, back_populates="watchgroups", cascade="all,delete")

    @hybrid_property
    def channelcount(self):
        return object_session(self).query(Watchgroup).where(Watchgroup.id == self.id).join(TelegramChannel, Watchgroup.channels).count()

    @channelcount.expression
    def channelcount(self):
        return select([func.count(Watchgroup.id)]).where(Watchgroup.id == self.id).join(TelegramChannel, Watchgroup.channels)

    @hybrid_property
    def webhookcount(self):
        return object_session(self).query(Watchgroup).where(Watchgroup.id == self.id).join(Webhook, Watchgroup.webhooks).count()

    @webhookcount.expression
    def webhookcount(self):
        return select([func.count(Watchgroup.id)]).where(Watchgroup.id == self.id).join(Webhook, Watchgroup.webhooks)


class TelegramChannel(db):
    """A Telegram channel."""

    def __repr__(self):
        return f'<TelegramChannel id="{self.id}" name="{self.name}" registered={self.registered}>'

    __tablename__ = "tgchannel"
    id = Column(BigInteger, unique=True, primary_key=True)  # Telegram Chat ID.
    name = Column(String(128))  # TODO: auto-generated
    registered = Column(Boolean, server_default='1')  # Whether or not this channel can be used.

    # TODO: use many-to-many for telegram channel to watchgroup relationship instead of one to many?
    watchgroupid = Column(String(128), ForeignKey('tgwatchgroup.id'))
    webhooks = relationship("Webhook", secondary=dwh2tgc_association_table, back_populates="watched", cascade="all,delete")

    @hybrid_property
    def watchgroupcount(self):
        return object_session(self).query(TelegramChannel).where(TelegramChannel.id == self.id).join(TelegramChannel, Watchgroup.channels).count()

    @watchgroupcount.expression
    def watchgroupcount(self):
        return select([func.count(TelegramChannel.id)]).where(TelegramChannel.id == self.id).join(TelegramChannel, Watchgroup.channels)

    @hybrid_property
    def webhookcount(self):
        return object_session(self).query(TelegramChannel).where(TelegramChannel.id == self.id).join(TelegramChannel, Webhook.watched).count()

    @webhookcount.expression
    def webhookcount(self):
        return select([func.count(TelegramChannel.id)]).where(TelegramChannel.id == self.id).join(TelegramChannel, Webhook.watched)