import os
from alembic import context
from app.database import make_engine
from app.models import Base
from app import memory_models  # Register memory tables for metadata inspection.
if context.is_offline_mode():
    context.configure(url=os.environ["DATABASE_URL"], target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(os.getenv("MIGRATION_DATABASE_URL") or os.environ["DATABASE_URL"])
    with engine.connect() as connection:
        sqlite=connection.dialect.name=='sqlite'
        if sqlite:
            # Rebuild tables atomically while preserving/validating all foreign keys.
            connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
            connection.commit()
            connection.exec_driver_sql('BEGIN')
        context.configure(connection=connection, target_metadata=Base.metadata)
        try:
            with context.begin_transaction():
                context.run_migrations()
            if sqlite:
                if connection.exec_driver_sql('PRAGMA foreign_key_check').fetchone():
                    raise RuntimeError('Migration foreign key validation failed')
                connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if sqlite:connection.exec_driver_sql('PRAGMA foreign_keys=ON')
