from typing import Tuple
from pydantic import BaseModel, BaseSettings, root_validator, PostgresDsn
from pydantic.env_settings import SettingsSourceCallable

# pylint: disable=missing-class-docstring, missing-function-docstring, invalid-name

class TelegramConfig(BaseModel):
    sessionfile: str = "tgbridge.session"  # TODO: make pathlike
    api_id: int
    api_hash: str

class LocalStorageConfig(BaseModel):
    enabled: bool = False
    file_prefix: str  # TODO: make pathlike
    url_prefix: str  # TODO: make HTTP pathlike

class B2StorageConfig(BaseModel):
    enabled: bool = False
    api_id: str
    api_key: str
    url_prefix: str
    bucket_name: str = None
    bucket_id: str = None
    file_prefix: str = None  # TODO: make pathlike

    @root_validator
    def name_or_id(cls, values):
        # pylint: disable=no-self-argument
        name, id = values.get('bucket_name'), values.get('bucket_id')
        if name and id:
            raise ValueError("Only one of bucket_name or bucket_id can be set")
        elif not name and not id:
            raise ValueError("One of bucket_name or bucket_id must be set")

        return values

class StorageConfig(BaseModel):
    cache_dir: str  # TODO: make pathlike
    local: LocalStorageConfig = None  # needs one w/o enabled or both w/ enabled
    b2: B2StorageConfig = None

    @root_validator
    def one_handler(cls, values):
        # pylint: disable=no-self-argument
        local, b2 = values.get('local'), values.get('b2')
        if not local and not b2:
            raise ValueError("One storage handler must be configured")
        elif local.enabled and b2.enabled:
            raise ValueError("Only one storage handler can be enabled")
        
        return values

class Settings(BaseSettings):
    telegram: TelegramConfig
    storage: StorageConfig
    dburl: PostgresDsn  # TODO: allow building instead of raw db url

    class Config:
        env_nested_delimiter = '__'
        env_prefix = "tgbridge_"
        # Make environment variables take precendence over the config file.
        @classmethod
        def customise_sources(
            cls,
            init_settings: SettingsSourceCallable,
            env_settings: SettingsSourceCallable,
            file_secret_settings: SettingsSourceCallable,
        ) -> Tuple[SettingsSourceCallable, ...]:
            return env_settings, init_settings, file_secret_settings
