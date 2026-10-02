"""场景 1.2：MySQL 建库、迁移并创建最小权限账号。"""
import os
import re
import pymysql
from sqlalchemy.engine import URL
from alembic import command
from alembic.config import Config
from app.config import ROOT


def main() -> None:
    """场景 1.2：root 只用于显式部署任务，不传给运行中的 API。"""
    host = os.environ.get('MYSQL_HOST', '127.0.0.1')
    port = int(os.environ.get('MYSQL_PORT', '3306'))
    database = os.environ.get('MYSQL_DATABASE', 'threadpilot')
    app_user = os.environ.get('MYSQL_APP_USER', 'threadpilot_app')
    ai_user = os.environ.get('MYSQL_AI_USER', 'threadpilot_ai')
    if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', value) for value in (database, app_user, ai_user)):
        raise ValueError('Invalid database/account identifier')
    root_password = os.environ['MYSQL_ROOT_PASSWORD']
    passwords = {user: os.environ[var] for user, var in [(app_user, 'MYSQL_APP_PASSWORD'), (ai_user, 'MYSQL_AI_PASSWORD')]}
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{24,128}', value) or value.startswith('replace_') for value in passwords.values()):
        raise ValueError('Use distinct URL-safe passwords of at least 24 characters')
    if len(set([root_password, *passwords.values()])) != 3:
        raise ValueError('Root, application and AI passwords must differ')
    with pymysql.connect(host=host, port=port, user='root', password=root_password, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4')
    os.environ['DATABASE_URL'] = URL.create('mysql+pymysql', username='root', password=root_password, host=host, port=port, database=database).render_as_string(hide_password=False)
    command.upgrade(Config(str(ROOT / 'backend/alembic.ini')), 'head')
    with pymysql.connect(host=host, port=port, user='root', password=root_password, autocommit=True) as connection:
        with connection.cursor() as cursor:
            for user, password in passwords.items():
                cursor.execute('CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s', (user, '%', password))
                cursor.execute('ALTER USER %s@%s IDENTIFIED BY %s', (user, '%', password))
                cursor.execute('REVOKE ALL PRIVILEGES, GRANT OPTION FROM %s@%s', (user, '%'))
            cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{database}`.* TO %s@%s", (app_user, "%"))
            for table in ('orders', 'production_log', 'workshops'):
                cursor.execute(f"GRANT SELECT ON `{database}`.`{table}` TO %s@%s", (ai_user, "%"))
    print('Migrations and separate application/SELECT-only accounts are ready.')


if __name__ == '__main__':
    main()
