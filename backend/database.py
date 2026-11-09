"""Database URL resolution and dialect-specific connection setup (no secret logging)."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url

from .config import settings


def database_url(config=settings):
    if config.database_url:
        try:
            url = make_url(config.database_url)
        except Exception:
            raise ValueError("DATABASE_URL 格式无效，请检查本地数据库配置") from None
    elif config.mysql_host:
        url = URL.create(
            "mysql+pymysql",
            username=config.mysql_user,
            password=config.mysql_password,
            host=config.mysql_host,
            port=config.mysql_port,
            database=config.mysql_database,
            query={"charset": "utf8mb4"},
        )
    else:
        url = URL.create("sqlite", database=str(config.storage / "studio.db"))
    if url.drivername in {"mysql", "mysql+mysqldb"}:
        url = url.set(drivername="mysql+pymysql")
    if url.drivername not in {"sqlite", "mysql+pymysql"}:
        raise ValueError("当前仅支持 SQLite 或 mysql+pymysql 数据库")
    if url.drivername == "mysql+pymysql":
        if not url.host or not url.database or not url.username:
            raise ValueError("MySQL 配置需包含主机、数据库名称和用户名")
        url = url.update_query_dict({"charset": "utf8mb4"})
    return url


def build_engine(url, config=settings):
    if url.get_backend_name() == "sqlite":
        result = create_engine(
            url, connect_args={"check_same_thread": False, "timeout": 30}, hide_parameters=True
        )

        @event.listens_for(result, "connect")
        def setup_sqlite(connection, _):
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=30000")

        return result
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=config.database_pool_recycle,
        pool_size=config.database_pool_size,
        max_overflow=5,
        pool_timeout=30,
        isolation_level="READ COMMITTED",
        hide_parameters=True,
        connect_args={"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30},
    )


def public_database_info(engine):
    return {
        "driver": engine.dialect.name,
        "host": engine.url.host,
        "port": engine.url.port,
        "database": engine.url.database if engine.dialect.name == "mysql" else "studio.db",
    }
