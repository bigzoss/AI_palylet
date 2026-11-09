"""Manage the workspace's private MySQL instance. Never print credentials."""

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
import pymysql
from dotenv import set_key
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".runtime" / "mysql"
VERSION = "8.4.13"
ARCHIVE = f"mysql-{VERSION}-winx64.zip"
ARCHIVE_MD5 = "7b94489d5524dea9b27097068bea25a8"
CREDENTIALS = LOCAL / "credentials.json"
PORT = 13306


def server_root():
    """MySQL's Windows path handling requires ASCII option-file paths on this host."""
    if str(LOCAL).isascii():
        return LOCAL
    base = Path(os.environ["LOCALAPPDATA"]) / "Framecraft"
    alias = base / ("mysql-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12])
    if not str(alias).isascii():
        raise RuntimeError("MySQL requires an ASCII installation alias on this Windows host")
    base.mkdir(parents=True, exist_ok=True)
    if alias.exists():
        if alias.resolve() != LOCAL.resolve():
            raise RuntimeError("MySQL ASCII alias belongs to a different target")
    else:

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        command = (
            "New-Item -ItemType Junction -Path "
            + quote(alias)
            + " -Target "
            + quote(LOCAL)
            + " -ErrorAction Stop | Out-Null"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError("Could not create ASCII directory junction for local MySQL")
    return alias


def credentials():
    if not CREDENTIALS.is_file():
        raise RuntimeError("Local MySQL is not configured; run setup first")
    return json.loads(CREDENTIALS.read_text(encoding="utf-8"))


def app_url(value=None):
    value = value or credentials()
    return URL.create(
        "mysql+pymysql",
        username=value["user"],
        password=value["password"],
        host="127.0.0.1",
        port=value["port"],
        database=value["database"],
        query={"charset": "utf8mb4"},
    )


def binary():
    path = server_root() / f"mysql-{VERSION}-winx64" / "bin" / "mysqld.exe"
    if not path.is_file():
        raise RuntimeError("MySQL binary missing; run setup first")
    return path


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def root_connection(value, allow_empty=False):
    try:
        return pymysql.connect(
            host="127.0.0.1",
            port=value["port"],
            user="root",
            password=value["root_password"],
            charset="utf8mb4",
            connect_timeout=3,
        )
    except pymysql.err.OperationalError as exc:
        if allow_empty and exc.args[0] == 1045:
            return pymysql.connect(
                host="127.0.0.1",
                port=value["port"],
                user="root",
                password="",
                charset="utf8mb4",
                connect_timeout=3,
            )
        raise


def verify_instance(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@datadir, @@port")
        directory, port = cursor.fetchone()
    if Path(directory).resolve() != (LOCAL / "data").resolve() or int(port) != PORT:
        raise RuntimeError("Port belongs to a different MySQL instance; refusing to modify it")


def start_instance(allow_empty=False):
    value = credentials()
    process = None
    if not listening(value["port"]):
        with (LOCAL / "console.log").open("ab") as log:
            process = subprocess.Popen(
                [str(binary()), f"--defaults-file={server_root() / 'my.ini'}"],
                cwd=server_root(),
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        (LOCAL / "launcher.pid").write_text(str(process.pid), encoding="ascii")
    for _ in range(60):
        if process and process.poll() is not None:
            raise RuntimeError("MySQL exited; inspect .runtime/mysql/mysql.err.log")
        try:
            connection = root_connection(value, allow_empty)
            verify_instance(connection)
            return connection
        except pymysql.err.OperationalError as exc:
            if exc.args[0] not in {2003, 2013, 2006}:
                raise
            time.sleep(0.5)
    raise RuntimeError("MySQL startup timed out; inspect local logs")


def setup():
    LOCAL.mkdir(parents=True, exist_ok=True)
    archive = LOCAL / ARCHIVE
    if not archive.is_file():
        with httpx.stream(
            "GET", f"https://cdn.mysql.com/Downloads/MySQL-8.4/{ARCHIVE}", follow_redirects=True, timeout=60
        ) as response:
            response.raise_for_status()
            with archive.open("wb") as out:
                for chunk in response.iter_bytes(1024 * 1024):
                    out.write(chunk)
    if hashlib.md5(archive.read_bytes()).hexdigest() != ARCHIVE_MD5:
        raise RuntimeError("MySQL archive integrity verification failed")
    exe = LOCAL / f"mysql-{VERSION}-winx64" / "bin" / "mysqld.exe"
    if not exe.exists():
        print("Extracting verified MySQL archive...", flush=True)
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                target = (LOCAL / entry.filename).resolve()
                if (
                    not target.is_relative_to(LOCAL.resolve())
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise RuntimeError("Unsafe archive path")
            bundle.extractall(LOCAL)
    if not CREDENTIALS.exists():
        if (LOCAL / "data").exists() and any((LOCAL / "data").iterdir()):
            raise RuntimeError("Existing data without credentials; refusing to reset it")
        value = {
            "host": "127.0.0.1",
            "port": PORT,
            "database": "framecraft",
            "user": "framecraft",
            "password": secrets.token_urlsafe(32),
            "root_password": secrets.token_urlsafe(40),
        }
        CREDENTIALS.write_text(json.dumps(value, indent=2), encoding="utf-8")
    runtime = server_root()
    config = "\n".join(
        [
            "[mysqld]",
            f'basedir="{(runtime / f"mysql-{VERSION}-winx64").as_posix()}"',
            f'datadir="{(runtime / "data").as_posix()}"',
            f"port={PORT}",
            "bind-address=127.0.0.1",
            "mysqlx=0",
            "character-set-server=utf8mb4",
            "collation-server=utf8mb4_bin",
            "innodb-buffer-pool-size=128M",
            "max-allowed-packet=64M",
            "skip-log-bin",
            f'log-error="{(runtime / "mysql.err.log").as_posix()}"',
            f'pid-file="{(runtime / "mysql.pid").as_posix()}"',
            "",
        ]
    )
    (LOCAL / "my.ini").write_text(config, encoding="utf-8")
    if not (LOCAL / "data" / "auto.cnf").is_file():
        print("Initializing isolated MySQL data directory...", flush=True)
        with (LOCAL / "initialize.log").open("ab") as log:
            result = subprocess.run(
                [str(binary()), f"--defaults-file={runtime / 'my.ini'}", "--initialize-insecure"],
                stdout=log,
                stderr=log,
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if result.returncode:
            raise RuntimeError("MySQL initialization failed; inspect local logs")
    value = credentials()
    with start_instance(allow_empty=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (value["root_password"],))
            cursor.execute(
                "CREATE DATABASE IF NOT EXISTS framecraft CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
            )
            for host in ["localhost", "127.0.0.1"]:
                cursor.execute(
                    "CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s",
                    (value["user"], host, value["password"]),
                )
                cursor.execute("GRANT ALL PRIVILEGES ON framecraft.* TO %s@%s", (value["user"], host))
        connection.commit()
    print("MySQL configured: 127.0.0.1:13306 / framecraft (credentials stored locally; not displayed)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "start", "stop", "status", "activate"])
    args = parser.parse_args()
    if args.action == "setup":
        setup()
    elif args.action == "start":
        start_instance().close()
        print("Local MySQL ready: 127.0.0.1:13306")
    elif args.action == "stop":
        value = credentials()
        if listening(value["port"]):
            with root_connection(value) as connection:
                verify_instance(connection)
                with connection.cursor() as cursor:
                    cursor.execute("SHUTDOWN")
            for _ in range(30):
                if not listening(value["port"]):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("MySQL shutdown still in progress")
        print("Local MySQL stopped")
    elif args.action == "activate":
        target = ROOT / ".env.local"
        if target.is_symlink():
            raise RuntimeError("Refusing to write through an env-file symlink")
        set_key(str(target), "DATABASE_URL", app_url().render_as_string(hide_password=False))
        set_key(str(target), "MYSQL_LOCAL_MANAGED", "true")
        print("Database settings saved to .env.local; credentials not displayed")
    else:
        value = credentials()
        with root_connection(value) as connection:
            verify_instance(connection)
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                version = cursor.fetchone()[0]
        print(
            json.dumps(
                {
                    "version": version,
                    "host": "127.0.0.1",
                    "port": value["port"],
                    "database": value["database"],
                    "user": value["user"],
                },
                ensure_ascii=True,
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            print(str(exc), file=sys.stderr)
        else:
            code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
            print(
                f"MySQL operation failed: {type(exc).__name__} (code={code}); credentials omitted",
                file=sys.stderr,
            )
        raise SystemExit(1)
