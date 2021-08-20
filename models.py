from sqlalchemy import Column, Computed, String, BigInteger, Boolean, Sequence, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import text

db = declarative_base()

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

    # TODO: mandate that webhooks must be added from the same server they were created from
    id = Column(String(128), primary_key=True, server_default=text("gen_random_uuid()"))
    url = Column(String(128), nullable=False, unique=True)  # The webhook.
    serverid = Column(BigInteger, nullable=False)  # Server that created this webhook.

    watchgroups = relationship("Watchgroup", secondary=dwh2wg_association_table)
    watched = relationship("TelegramChannel", secondary=dwh2tgc_association_table)

    active = Column(Boolean, server_default='1')

class Watchgroup(db):
    __tablename__ = "tgwatchgroup"

    id = Column(String(128), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(128), unique=True, nullable=False)

    channels = relationship("TelegramChannel")
    webhooks = relationship("Webhook", secondary=dwh2wg_association_table, back_populates="watchgroups")

class TelegramChannel(db):
    """A Telegram channel."""
    __tablename__ = "tgchannel"
    id = Column(BigInteger, unique=True, primary_key=True)  # Telegram Chat ID.
    name = Column(String(128))  # TODO: auto-generated
    registered = Column(Boolean, server_default='1')  # Whether or not this channel can be used.

    # TODO: use many-to-many for telegram channel to watchgroup relationship instead of one to many?
    watchgroupid = Column(String(128), ForeignKey('tgwatchgroup.id'))
    webhooks = relationship("Webhook", secondary=dwh2tgc_association_table, back_populates="watched")
