"""Isolated copy of app-executer-main with demo bots, to reproduce bugs and test changes without touching the real app.

The copy gets APP_NAME 'app-executer-main-sandbox', so it has its own %LOCALAPPDATA% state, language setting and driver
task ('app-executer-main-sandbox driver'). Layout created under --dest:

    <dest>/projects/app-executer-main/         copy of src/ + config/ + setup (setup-app-executer-main-sandbox.ps1)
    <dest>/projects/rpa-bot-demo-ventas/       tqdm-like progress + INFO/WARNING logs, exits 0
    <dest>/projects/rpa-bot-demo-sap/          flattened Selenium WARNINGs + ERROR + Python traceback, exits 1
    <dest>/projects/rpa-bot-demo-sin-venv/     no venv (diagnostic "No tiene entorno virtual")
    <dest>/kreton-watch/                       the demo bots' logs (same format as kreton_tools_kit / pi_kreton_rpa)
    <dest>/common/.env                         fake log database credentials (OWNER_SQL_*)
    <dest>/fake-mysql/venv + logs.db           LOG_DB.PYTHON of the copy: a venv whose "pymysql" writes to a sqlite
                                               file, so "Upload logs" and "Server logs" never reach a real server

Usage (from the app folder, with the app's venv):
    .\\venv-app-executer-main\\Scripts\\python.exe .claude\\skills\\app-executer-main\\scripts\\make_sandbox.py --dest <dir> [--max-parallel N] [--fresh]
Demo speed: env DEMO_SECONDS (seconds per step, default 0.4) is inherited by the runner and the bots.
"""
import os, sys, json, shutil, argparse, subprocess

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

VENTAS = r'''"""Demo bot (sandbox): Pipeline-like logs in watch format, tqdm-like progress on stderr, exits 0."""
import os, sys, time
from datetime import datetime

GROUP_LOG = 'rpa-bot-demo-ventas'
WATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'kreton-watch', GROUP_LOG)
os.makedirs(WATCH, exist_ok=True)
RUN = datetime.now().strftime('%Y%m%d%H%M%S')
STEP = float(os.environ.get('DEMO_SECONDS', '0.4'))


def log(level, msg):
    with open(os.path.join(WATCH, f'{RUN}.txt'), 'a', encoding='utf-8') as f:
        f.write(f"{GROUP_LOG}§{RUN}§{datetime.now():%Y-%m-%d %H:%M:%S}§{level}§{msg}\n")


log('INFO', '.json arguments loaded from src\\..\\config\\config.json (4 keys)')
log('INFO', 'execute: src\\rpa_bot_download_ventas.py')
total = 40
for n in range(total + 1):
    pct = n * 100 // total
    bar = '#' * (pct // 10) + ' ' * (10 - pct // 10)
    sys.stderr.write(f'\rdownload_ventas: {pct:3d}%|{bar}| {n}/{total} [00:00<00:00]')
    sys.stderr.flush()
    if n and n % 10 == 0:
        log('INFO', f'page {n // 10}/4 downloaded ({n * 250} rows)')
    time.sleep(STEP)
sys.stderr.write('\n')
log('WARNING', 'store 0412 without sales this week')
log('INFO', 'pipeline finished: 1/1 OK')
'''

SAP = r'''"""Demo bot (sandbox): a flattened Selenium error as the team's log helper writes it, then a traceback; exits 1."""
import os, time
from datetime import datetime

GROUP_LOG = 'rpa-bot-demo-sap'
WATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'kreton-watch', GROUP_LOG)
os.makedirs(WATCH, exist_ok=True)
RUN = datetime.now().strftime('%Y%m%d%H%M%S')
STEP = float(os.environ.get('DEMO_SECONDS', '0.4'))


def log(level, msg):
    with open(os.path.join(WATCH, f'{RUN}.txt'), 'a', encoding='utf-8') as f:
        f.write(f"{GROUP_LOG}§{RUN}§{datetime.now():%Y-%m-%d %H:%M:%S}§{level}§{msg}\n")
    time.sleep(STEP)


log('INFO', 'execute: src\\rpa_bot_download_data_sap.py')
log('INFO', 'success login in portal')
for n in range(1, 4):
    log('WARNING', f'error to click tried ({n}/3): Message: no such element: Unable to locate element: '
                   '{"method":"xpath","selector":"//div[contains(@title, \'Get Variant\')]"} (Session info: chrome=154.0.8037.98); '
                   'For documentation on this error, please visit: https://www.selenium.dev/documentation/webdriver/troubleshooting/errors '
                   'Stacktrace: chromedriver!GetHandleVerifier [0x7ff67e849d55+5a55] chromedriver!(No symbol) [0x7ff67e76f540] '
                   'KERNEL32!BaseThreadInitThunk [0x7ffd150dcd87+17] ntdll!RtlUserThreadStart [0x7ffd1614caec+2c]')
log('ERROR', 'step 2/3 failed - can not download data from SAP: variant not found')


def download():
    raise TimeoutError('download not finished after 5 attempts')


download()
'''

CONFIG_JSON = {'SQL_SCHEMA': 'bbdd_demo_ventas', 'TIMEOUT': 600, 'MAIL_RESPONSIBLE': 'responsable@example.com',
               'LIST_MARKETS_EXCLUIDE': ['M001', 'M002']}
CONFIG_ENV = 'PORTAL_USER="usuario.demo"\nPORTAL_PASSWORD="no-es-una-clave-real"\n'
COMMON_ENV = 'OWNER_SQL_HOST=127.0.0.1\nOWNER_SQL_PORT=3306\nOWNER_SQL_USER=sandbox\nOWNER_SQL_PASSWORD="no-es-una-clave-real"\n'

# stand-in for pymysql with the calls LogDatabase makes, over <dest>/fake-mysql/logs.db
FAKE_PYMYSQL = r'''"""Sandbox stand-in for pymysql: the calls the app makes, over a sqlite file. It never reaches a real server."""
import os, re, sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'logs.db')


class Cursor:
    def __init__(self, conn):
        self.cur = conn.cursor()
        self.rows = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @staticmethod
    def _sql(sql):
        return re.sub(r'`[^`]+`\.`([^`]+)`', r'\1', sql).replace('%s', '?')

    def execute(self, sql, params=()):
        match = re.match(r'SHOW COLUMNS FROM (\S+)', self._sql(sql))
        if match:
            self.rows = [(row[1],) for row in self.cur.execute(f'PRAGMA table_info({match.group(1)})')]
            return
        self.rows = None
        self.cur.execute(self._sql(sql), params)

    def executemany(self, sql, seq):
        self.cur.executemany(self._sql(sql), seq)

    def fetchall(self):
        return self.rows if self.rows is not None else self.cur.fetchall()

    def fetchone(self):
        return self.rows[0] if self.rows else self.cur.fetchone()


class Connection:
    def __init__(self, database):
        self.db = sqlite3.connect(DB)
        self.db.execute('CREATE TABLE IF NOT EXISTS tb_logs_watch_bots (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                        'process_name TEXT NOT NULL, id_process INTEGER NOT NULL, timestamp_log TEXT NOT NULL, '
                        'type_log TEXT NOT NULL, message TEXT, update_at TEXT NOT NULL)')
        self.db.commit()

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        self.db.close()


def connect(host, port, user, password, database, **kwargs):
    return Connection(database)
'''


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dest', required=True, help='empty folder (use the session scratchpad)')
    parser.add_argument('--max-parallel', type=int, default=1, help='MAX_PARALLEL of the copy (1 makes the queue easy to see)')
    parser.add_argument('--fresh', action='store_true', help='delete <dest> and the sandbox state first')
    args = parser.parse_args()

    dest = os.path.abspath(args.dest)
    projects = os.path.join(dest, 'projects')
    copy = os.path.join(projects, 'app-executer-main')
    if args.fresh:
        shutil.rmtree(dest, ignore_errors=True)
    if os.path.exists(copy):
        sys.exit(f'{copy} already exists (use --fresh to recreate it)')

    # app copy with its own identity
    for name in ('src', 'config'):
        shutil.copytree(os.path.join(APP, name), os.path.join(copy, name), ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy(os.path.join(APP, 'requirements.txt'), copy)
    with open(os.path.join(copy, 'config', 'config.json'), encoding='utf-8') as f:
        config = json.load(f)
    fake_python = os.path.join(dest, 'fake-mysql', 'venv', 'Scripts', 'python.exe')
    config.update(APP_NAME='app-executer-main-sandbox', APP_ID='kreton.rpa.app-executer-main-sandbox', MAX_PARALLEL=args.max_parallel,
                  WATCH_PATH='../../kreton-watch')
    config['LOG_DB'].update(PYTHON=fake_python, ENV_FILE='../../common/.env')
    write(os.path.join(copy, 'config', 'config.json'), json.dumps(config, indent=4, ensure_ascii=False) + '\n')
    write(os.path.join(copy, 'config', 'schedules.json'), '{}\n')
    # ScheduledPage.install_driver looks for setup-<APP_NAME>.ps1
    shutil.copy(os.path.join(APP, 'setup-app-executer-main.ps1'), os.path.join(copy, 'setup-app-executer-main-sandbox.ps1'))
    state = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), config['APP_NAME'])
    if args.fresh:
        shutil.rmtree(state, ignore_errors=True)

    # demo bots
    write(os.path.join(projects, 'rpa-bot-demo-ventas', 'src', 'main.py'), VENTAS)
    write(os.path.join(projects, 'rpa-bot-demo-ventas', 'config', 'config.json'), json.dumps(CONFIG_JSON, indent=4) + '\n')
    write(os.path.join(projects, 'rpa-bot-demo-ventas', 'config', '.env'), CONFIG_ENV)
    write(os.path.join(projects, 'rpa-bot-demo-sap', 'src', 'main.py'), SAP)
    write(os.path.join(projects, 'rpa-bot-demo-sin-venv', 'src', 'main.py'), "GROUP_LOG = 'rpa-bot-demo-sin-venv'\n")
    # the demo bots only need a python.exe in venv-<bot> (stdlib); without pip it is faster and doesn't hit ensurepip errors
    for bot in ('rpa-bot-demo-ventas', 'rpa-bot-demo-sap'):
        subprocess.run([sys.executable, '-m', 'venv', '--without-pip', os.path.join(projects, bot, f'venv-{bot}')], check=True)
    os.makedirs(os.path.join(dest, 'kreton-watch'), exist_ok=True)

    # fake log database: its own venv with the pymysql stand-in, and fake credentials
    venv = os.path.join(dest, 'fake-mysql', 'venv')
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', venv], check=True)
    write(os.path.join(venv, 'Lib', 'site-packages', 'pymysql', '__init__.py'), FAKE_PYMYSQL)
    write(os.path.join(dest, 'common', '.env'), COMMON_ENV)

    py = sys.executable
    main_py = os.path.join(copy, 'src', 'main.py')
    print(f'''Sandbox ready: {dest}
  state (own, per PC): {os.path.join(state, 'scheduler')}

  UI:              "{py}" "{main_py}"
  one tick:        "{py}" "{main_py}" --tick
  one run:         "{py}" "{main_py}" --run rpa-bot-demo-ventas
  log database:    "{fake_python}" "{main_py}" --db test|upload|query   (fake: {os.path.join(dest, 'fake-mysql', 'logs.db')})
  driver (real Windows task 'app-executer-main-sandbox driver'):
    install:       powershell -NoProfile -ExecutionPolicy Bypass -File "{os.path.join(copy, 'setup-app-executer-main-sandbox.ps1')}" -NoShortcut
    remove (ALWAYS at the end): same command with -RemoveScheduler
  in a script:     sys.path.insert(0, r"{os.path.join(copy, 'src')}"); import main as m
                   app = m.App(r"{copy}", config)   # config = json.load(<copy>/config/config.json)
''')


if __name__ == '__main__':
    main()
