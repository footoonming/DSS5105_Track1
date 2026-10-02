"""场景 1.2：Alembic 从环境配置读取连接。"""
from alembic import context
from sqlalchemy import create_engine, pool
from app.config import Settings
from app.db.base import Base
from app import models

target_metadata = Base.metadata
url = Settings().database_url.get_secret_value()
if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
