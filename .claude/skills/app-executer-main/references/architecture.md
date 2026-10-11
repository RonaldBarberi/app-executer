# Arquitectura de app-executer-main

Para ubicar el código usa `Grep` con el nombre de la clase o método indicado; los números de línea cambian.

## 1. Estructura del proyecto

```
app-executer-main/
├── src/main.py                    toda la app (UI + scheduler + CLI)
├── config/config.json             configuración (ver tabla)
├── config/i18n.json               textos {"en": {...}, "es": {...}}, mismas claves y placeholders
├── config/schedules.json          horarios CRON_DRIVER (compartido, versionado)
├── config/assets/                 kreton.ico (ventana/barra de tareas/acceso directo), logo-<n>.png (logo de la cabecera, `App._image`)
├── setup-app-executer-main.ps1    venv + acceso directo (AUMID) + driver; flags -Desktop -NoShortcut -NoScheduler -RemoveScheduler
├── setup-app-executer-main.bat    lanzador del .ps1 (ExecutionPolicy Bypass) + pause
├── run-app-executer-main.bat      start pythonw src\main.py
├── tests/                         unittest: test_cron, test_scheduler, test_config, test_parsers, test_venv, test_log_db, test_i18n
└── docs/manual/                   manual de usuario por pestaña + 05-ajustes (+ img/)
```

### `config/config.json`

| Clave | Uso |
|---|---|
| `APP_NAME` | Nombre de la ventana, del estado por PC (`%LOCALAPPDATA%\<APP_NAME>`), de la tarea (`<APP_NAME> driver`) y del setup (`setup-<APP_NAME>.ps1`, que usa `ScheduledPage.install_driver`). |
| `APP_ID` | AppUserModelID de Windows. Lo fijan `App.__init__` y el acceso directo del setup, para que la barra de tareas agrupe la ventana con el ícono anclado. |
| `PROJECTS_PATH`, `WATCH_PATH` | Relativas a la raíz de la app: `..` (bots) y `../../kreton-watch` (logs; los escribe `kreton_tools_kit.log` en `~/HDFS/kreton-watch/<grupo>`). `WATCH_PATH` se cambia por PC en Ajustes. |
| `LOG_DB` | `PYTHON` (vacío = `find_db_python`), `ENV_FILE` (`../../common/.env`), `ENV_KEYS` {host, port, user, password → `OWNER_SQL_*`}, `DATABASE` (`bbdd_data_vault`), `TABLE` (`tb_logs_watch_bots`), `QUERY_LIMIT` (1000). Ajustes reemplaza `LOG_DB_EDITABLE` = PYTHON, ENV_FILE, DATABASE, TABLE. |
| `ASSETS_PATH`, `ICON_FILE` | Carpeta de assets e ícono `.ico`. |
| `EXCLUDED_PROJECTS` | Carpetas que no se listan. |
| `POLL_MS` | Frecuencia de lectura de la `RunView` (200 ms). |
| `MAX_LOG_LINES` | Eventos que guarda la tabla de una `RunView`. |
| `THEME_DEFAULT`, `THEMES` | Tema inicial y paletas `light`/`dark` (claves de color, ver §4). Marca KretoN: claro con acento teal `#225866`; oscuro con fondo teal y acento amarillo `#F2BB30` (`on_accent` oscuro, `ok` menta `#86DDD4`, `warning` naranja para no confundirse con el acento). |
| `I18N_FILE`, `LANGUAGE_DEFAULT` | Textos e idioma inicial (`en`). |
| `SCHEDULES_FILE`, `MAX_PARALLEL`, `MISSED_AFTER_MINUTES`, `HISTORY_DAYS` | Scheduler: archivo de horarios, cupos (2), margen de atraso antes de "missed" (5 min) y retención en días (30). |

## 2. Mapa de `src/main.py` (en orden)

| Sección / clase | Responsabilidad |
|---|---|
| `resolve`, `LocalizedError` | Textos que pueden ser `lambda` (siguen el cambio de idioma) y errores con clave i18n. |
| Anti-aliased drawing: `aa_image`, `sd_box`, `sd_segment`, `sd_convex`, `aa_round_rect`, `aa_circle`, `draw_icon` | Dibujo con antialiasing. Las formas se rasterizan como SDF a PNG RGBA (generados en Python puro y cacheados en `_AA_IMAGES`). Íconos: play, stop, refresh, moon, sun, eye, copy, alert, info. |
| `RoundButton` | Botón Canvas. Variantes `ghost`, `accent`, `danger`; `bg_key`, `set(text, icon)`, `set_disabled`; `text` puede ser lambda. |
| `InfoIcon`, `Pill`, `RoundBar` | Ícono `!`/`i`, insignia de estado (`kind` = clave de color con su `_soft`) y barra de progreso. |
| `RoundCorners`, `RoundField` | Redondeo de recuadros. `RoundCorners(app, frame, radius, border)` pone un canvas r×r en cada esquina (`place`, `bordermode='ignore'`). Pinta el fondo del padre (`master.bg_key`), el arco del borde (`border_key`) y el relleno (`frame.bg_key`), y los sube con `<Configure>` y `after_idle`. `RoundField` es la caja de un input (borde de acento con foco); `bind`/`focus_set` van al `widget`. Los usan `App.card` (radio 12), `App.soft_box` (8, sin borde), `themed_entry` y `themed_combobox` (estilo `Round.TCombobox`, sin borde propio). Las tarjetas con tabla llevan 6 px de relleno para que las esquinas no tapen las flechas del scrollbar. |
| `IssuesDialog` | Popup de diagnóstico de un bot (lista `project['issues']`, comando con **Copiar**). |
| `ProjectConfig` | Lee los archivos que carga el `Pipeline` del bot (`find_sources` con `ast` sobre `main.py`), aplica precedencia y escribe solo lo editado (`update_json` por spans, `update_env` por línea; conserva BOM y CRLF; revisa `mtime`). Enmascara secretos con `SECRET_RE`. |
| `JsonEditor`, `ConfigDialog` | Entrada de ejecución (tabla, búsqueda, edición en línea y JSON, confirmación, guardado). `on_accept` lanza la ejecución. |
| `ProjectRow` | Fila de Procesos (hover, `set_status(text, kind, running)`). |
| `RunView` | Vista de una ejecución que lee archivos: `.out` (tqdm y consola) y el log de kreton-watch. Mientras corre sigue el lock (`_refresh`); al terminar toma el registro del historial. Contiene los parsers (`parse_tqdm`, `parse_log_line`, `split_message`, `log_matches`, `continues_block`), la tabla de eventos, el filtro, la copia y `stop()`. `STATUSES` = estado → (clave i18n, color). |
| `item_status`, `trigger_text`, `short_time`, `duration_text`, `themed_entry` | Ayudantes de las páginas. |
| `ActivityRow`, `ActivitiesPage` | Pestaña Actividades: lista (running, queued y las que terminaron en esta sesión) y detalle (`RunView` o panel de cola). |
| `HistoryPage` | Pestaña Historial: filtros, tabla, detalle con `RunView` y "← Historial". Abajo: **Logs del servidor** (`open_server` → `ServerLogsView`) y **Subir logs a la BD** (`upload_logs`: cuenta los logs sin los de locks, confirma, `app.run_db('upload')` con avance en el botón y resumen). |
| `ScheduledPage`, `ScheduleEditor` | Pestaña Programación (tarjeta del driver, tabla, acciones) y editor de horario. |
| `SettingsDialog` | Ventana **Ajustes** (botón de la cabecera), modal y en dos columnas para caber en 1080 px. Izquierda: carpeta de logs; Python con pymysql; base y tabla; **Probar conexión** (`run_db('test', db=valores sin guardar)`). Derecha: `.env` y el recuadro de variables (nombre, qué lleva, OK/Falta; la contraseña solo "OK (oculta)") con un ejemplo para copiar. `_check` valida en vivo; `save` → `app.save_user_settings`. |
| `ServerLogsView` | Subpágina de Historial: filtros (proceso, nivel, texto, desde/hasta `AAAA-MM-DD`), `run_db('query')`, tabla (WARNING ámbar, ERROR/CRITICAL rojo), mensaje completo de la fila seleccionada y Ctrl+C. |
| `find_group_log`, `find_venv`, `iso`, `parse_time`, `process_started` | Utilidades del scheduler. `process_started(pid)` devuelve la hora de creación del proceso, para no confundir un PID reutilizado. |
| `CronExpression` | Parser de cron de 5 campos, `next_after`, `between`, `upcoming`, `describe(t)`. |
| `Scheduler` | Motor sin Tk: horarios, lock entre procesos (`locked()`, msvcrt, **no reentrante**), estado, locks por bot, historial, `tick`, `request_run`, `cancel_queued`, `stop`, `run` (runner), `_prune`, `driver_status`, `set_paused_here`. |
| Settings and log database: `settings_file`, `read_settings`, `apply_settings`, `find_db_python`, `has_pymysql`, `parse_watch_log`, `watch_logs`, `same_path`, `LogDatabase`, `run_db_command` | Ajustes por PC y base de datos de logs (ver §9). |
| `App` | Ventana principal: cabecera, pestañas (`show_tab`), Procesos (`load_projects`, `_diagnose`), `refresh_ui` (bucle de 1 s en `_ui_loop`), `run_project`, `_launch`, `_open_view`, tema (`apply_theme`), idioma (`t`, `toggle_language`), ventanas (`style_window`: barra de título oscura + `WM_SETICON`). Ajustes: `base_config` (config.json sin ajustes), `watch_name` (nombre de la carpeta de logs para las etiquetas), `save_user_settings`, `run_db`. |
| `main()` | CLI con argparse: sin argumentos abre la UI; `--tick`; `--run BOT --run-id --trigger --scheduled-for`; `--db test\|upload\|query --db-args JSON`. Aplica `apply_settings` antes de cualquier modo. Los errores de `--tick`/`--run` van a `driver.log`; `--db` los imprime como JSON. |

## 3. Estado por PC y esquemas

Directorio: `%LOCALAPPDATA%\<APP_NAME>\scheduler\` (`Scheduler.state_dir`).

| Archivo | Contenido |
|---|---|
| `.lock` | Archivo de `Scheduler.locked()`: lock de 1 byte con `msvcrt.locking`, para leer y escribir el estado sin choques entre la UI, el tick y los runners. |
| `state.json` | `last_tick` (ISO), `queue` `{bot: {trigger, scheduled_for, queued_at}}`, `paused_here` (bool), `pruned_on` (fecha). |
| `locks\<bot>.json` | Existe mientras el bot corre: `bot, run_id, trigger, scheduled_for, start, runner_pid, runner_started, out`, y después `child_pid`, `log` y `abort_requested`. |
| `runs\<bot>\<run_id>.out` | stdout + stderr del bot (bytes UTF-8, con los `\r` de tqdm). |
| `history.jsonl` | Una línea por evento (ver abajo). `Scheduler.history()` une `start` + `end` por `id` y ordena de más nuevo a más viejo. |
| `driver.log` | Tracebacks de `--tick` y `--run` (que corren con `pythonw`, sin consola). |

Además, `%LOCALAPPDATA%\<APP_NAME>\settings.json` guarda las preferencias del PC: `{"LANGUAGE": "es", "WATCH_PATH": "C:\\...\\kreton-watch", "LOG_DB": {"PYTHON": "", "ENV_FILE": "...", "DATABASE": "...", "TABLE": "..."}}`.

Eventos de `history.jsonl`:

| `event` | Campos |
|---|---|
| `start` | `id` (= `run_id`, `YYYYmmddHHMMSSfff-<bot>`), `bot`, `trigger` (`manual`/`cron`), `scheduled_for`, `start`, `out` |
| `end` | `id`, `bot`, `end`, `status` (`succeeded`, `failed`, `aborted`, `start_failed`, `interrupted`), `code`, `log` |
| `missed` | `id`, `bot`, `expr`, `count`, `first`, `last`, `time` |
| `queued` | `id`, `bot`, `trigger`, `scheduled_for`, `time`, `reason` (`already_running`/`max_parallel`) |
| `cancelled` | `id`, `bot`, `trigger`, `time` |

`_prune` (una vez al día, desde el tick) conserva un `id` entero si su marca de tiempo **más nueva** está dentro de `HISTORY_DAYS`, y borra los `.out` viejos por `mtime`.

## 4. Ciclo de una ejecución

```
UI: Iniciar ejecución → ConfigDialog → App._launch → Scheduler.request_run(bot, 'manual')
Driver: cada minuto → main.py --tick → Scheduler.tick()
      │
      ├─ (bajo locked()) running(cleanup) · _drain(cola) · por bot ENABLED: CronExpression.between(last_tick, now)
      │     tarde > MISSED_AFTER_MINUTES → evento missed (uno por expresión) · a tiempo → _request(bot,'cron',due)
      ├─ _request: bot corriendo o len(running) >= MAX_PARALLEL → queue[bot] (máx 1) + evento queued
      │            si no → _launch: _spawn(pythonw main.py --run ...) DETACHED + BREAKAWAY_FROM_JOB,
      │                     escribe locks\<bot>.json + evento start
      ▼
Runner (main.py --run): Popen(<find_venv>\Scripts\python.exe src\main.py, stdout→.out, CREATE_NO_WINDOW)
      ├─ _update_lock(child_pid) · cada 1 s busca el log nuevo en kreton-watch/<GROUP_LOG> → lock['log']
      └─ al terminar (bajo locked()): borra el lock, escribe el evento end (status por código / abort_requested),
         y _drain(cola) → lanza lo que esperaba
UI: refresh_ui (1 s) lee running()/queue → Activities, filas de Procesos, contador de la pestaña
    RunView._poll (POLL_MS) lee .out + log; _refresh sigue el lock y, sin lock, toma el end del historial
```

- **Detener:** `Scheduler.stop(bot)` marca `abort_requested` en el lock y ejecuta `taskkill /T /F` sobre `child_pid` (o sobre el runner). El runner lo registra como `aborted`.
- **Lock huérfano:** si el runner muere, el siguiente `running(cleanup=True)` (tick o `request_run`) borra el lock y escribe `end` con `interrupted`.
- **`GROUP_LOG`:** `find_group_log` busca `GROUP_LOG = '...'` o `log.set_group('...')`. Si no lo encuentra, usa el nombre de la carpeta.

## 5. Formatos que se interpretan

- **Log de kreton-watch** (`pi_kreton_rpa.log`): `group§run_id§YYYY-MM-DD HH:MM:SS§LEVEL§mensaje`, con `\r\n`. `log._sanitize` cambia los saltos de línea del mensaje por espacios; `RunView.split_message` los reconstruye con `BREAK_RE` (Selenium: `(Session info:`, `For documentation…`, `Stacktrace:`, frames `mod!func`; Python: `Traceback…`, `File "…", line N`) y `EXCEPTION_RE` (solo dentro de un traceback).
- **tqdm:** `TQDM_RE` toma `desc: NN%|…| n/total`. La última actualización queda sin terminar con `\r`, así que `_read_out` también analiza el búfer pendiente.
- **Consola:** las líneas que no son tqdm se agregan en gris. Las líneas con sangría y la línea de la excepción continúan el bloque anterior (`continues_block`).
- **Cron:** 5 campos, `*`, `a-b`, listas, `/n`, nombres `JAN-DEC`/`SUN-SAT`, 7 = domingo, macros `@hourly…`. Si se restringen día del mes y día de la semana a la vez, es un OR, salvo que uno empiece con `*`. `describe()` cubre los patrones comunes y, si no, devuelve la expresión tal cual.

## 6. UI: cómo se construye

- **Tema:**
  - `App.register(widget, fn)` aplica `fn` ahora y en cada `apply_theme`.
  - Los helpers `app.frame`, `app.card`, `app.label(master, text, role, bg_key)` y `app.image_label` registran solos su tema; los widgets guardan `bg_key`/`fg_key`, y para refrescar uno se cambian y se llama `app.apply_widget(w)`.
  - Colores (`THEMES`): `bg, surface, hover, border, track, text, muted, faint, accent, accent_hover, on_accent, ok, warning, error` y `*_soft` (`accent_soft`, `ok_soft`, `warning_soft`, `error_soft`, `muted_soft`).
  - Roles de texto: `title, h1, h2, body, muted, caption, clock, value, pct, mono`.
  - Estilos ttk en `apply_theme`: `Config.Treeview`, `Log.Treeview`, scrollbars y `TCombobox` (su lista desplegable usa `option_add`).
- **Idioma:** `app.t(key, **params)`, con respaldo en `en`. Para que un texto cambie en vivo, pásalo como `lambda: app.t(...)`; los widgets lo resuelven con `resolve`. `toggle_language` reconstruye Procesos y llama `apply_theme` + `refresh_ui(full=True)`.
- **Escala:** `App.scale` = DPI/96 (proceso con DPI awareness); multiplica los tamaños en píxeles por `scale`.
- **Ventanas:** cada `Toplevel` llama `app.style_window(top)` (barra de título oscura + íconos `WM_SETICON` 24/16 × scale desde el `.ico`, sin reescalar).
- **Refresco:** `_ui_loop` llama `refresh_ui()` cada 1 s. Activities se refresca en cada ciclo; History, cuando cambia el `mtime` del historial o hay ejecuciones en curso; Scheduled, cada 10 s (y el driver, cada 30 s) o con `full=True`.

## 7. Diagnóstico (`App._diagnose`)

| Bloquea (`error`) | Aviso (`warning`) |
|---|---|
| Falta `src/`; `src/` sin `.py`; falta `src/main.py`; no hay venv (ver `find_venv`); el código menciona `pi_kreton_rpa` y no está en `site-packages` (es una búsqueda de texto, así que también salta por un comentario o docstring) | `GROUP_LOG` no encontrado; `stream_output=False` (sin barra de progreso: `project['no_progress']`) |

- **Venv del bot (`find_venv(path, name)`):** usa `venv-<bot>` si tiene `Scripts\python.exe`. Si no, toma la primera subcarpeta (en orden alfabético) con `pyvenv.cfg` y `Scripts\python.exe`, se llame como se llame (`.venv`, `venv`, `env`...). Si no hay ninguna, devuelve `venv-<bot>`, que no existe, y el diagnóstico marca "No tiene entorno virtual". La usan `_diagnose` (también para revisar `pi_kreton_rpa` y armar el `pip install` sugerido) y `Scheduler.run`. Tests: `tests/test_venv.py`.
- **Orden en Procesos:** `_discover_projects` devuelve los bots en orden alfabético y `load_projects` pone primero los `runnable` (con un ordenamiento estable, así que cada grupo queda alfabético). Solo afecta las filas de Procesos; `self.projects` conserva el orden alfabético.

## 8. Setup y driver

- `setup-app-executer-main.ps1`:
  1. Python 3.13 (`py -3.13` o `python`) + tkinter.
  2. venv (lo regenera con `--clear` si fue copiado de otro PC).
  3. `requirements.txt` (solo si tiene paquetes).
  4. Carpetas.
  5. Acceso directo (C# `IShellLinkW` + `IPropertyStore` para `System.AppUserModel.ID`).
  6. Driver: `Register-ScheduledTask`, acción `pythonw "src\main.py" --tick`, trigger `-Once` con repetición `PT1M` sin fin, `Interactive` + `Limited`, `IgnoreNew`, límite de 5 min y batería permitida.
- `Scheduler.driver_status()` lee `schtasks /Query /TN "<APP_NAME> driver" /XML` (independiente del idioma de Windows) y devuelve `missing`, `disabled`, `moved` (los argumentos no apuntan a este `main.py`) u `ok`.
- El driver solo corre con la sesión iniciada (también con el PC bloqueado). Sin sesión fallarían Outlook COM (`seend_mail`) y Excel COM (`read_nasca`). El usuario eligió no soportar "sin sesión".

## 9. Ajustes y base de datos de logs

- **Ajustes:** `apply_settings(config, read_settings(config))` reemplaza `WATCH_PATH` y los campos `LOG_DB_EDITABLE`. Lo aplican `main()` (todos los modos) y `App.__init__`. `save_user_settings` guarda, recalcula `app.watch_path` y `scheduler.watch_path`, y reconstruye Procesos.
- **Por qué otro Python:** la app es solo librería estándar y no hay cliente MySQL en la stdlib. `App.run_db(action, on_done, payload, on_progress, db)` lanza `<python con pymysql> main.py --db <action> --db-args <json>` (`CREATE_NO_WINDOW`, `PYTHONIOENCODING=utf-8`) en un hilo, lee líneas JSON (`{"progress": n, "total": t}`, `{"result": ...}` o `{"error": clave_i18n, "params": {...}}`) y llama `on_done(result, LocalizedError|None)` en el hilo de Tk. Una salida que no es JSON (traceback) se muestra como `db.err_generic`. El otro Python importa `main.py` entero, así que necesita tkinter (lo trae el Python de python.org).
- **`LogDatabase`:**
  - `credentials()` lee el `.env` con `ProjectConfig.parse_env` y valida que existan las 4 variables, que el puerto sea número y que los nombres cumplan `IDENT_RE`, porque van entre backticks.
  - `connect()` importa `pymysql` dentro del método.
  - `test()` revisa `COLUMNS` con `SHOW COLUMNS` y hace `COUNT(*)`.
  - `upload(watch, busy, emit)`: por archivo, `rename → .uploading` (falla si otro proceso lo tiene abierto → omitido), `parse_watch_log`, una transacción con `DELETE` de las mismas (process_name, id_process) + `executemany INSERT` + `commit`, y después `os.remove`. Si algo falla: `rollback`, vuelve al nombre original y suma a `failed`. Al final hace `rmdir` de las carpetas vacías. Devuelve `{files, rows, skipped, failed, error}`.
  - `query(filters)`: las más recientes primero, `QUERY_LIMIT + 1` para saber si hay más (`more`), y la lista de procesos.
- **Tabla real** (`bbdd_data_vault.tb_logs_watch_bots`, MySQL 8+): `id bigint unsigned AUTO_INCREMENT PK, process_name varchar(64), id_process decimal(16,0), timestamp_log datetime, type_log varchar(16), message text, update_at datetime`. No tiene llave única: el `DELETE` previo evita los duplicados. `_insert` recorta `process_name` a 64 y `type_log` a 16.
- **Sandbox:** `LOG_DB.PYTHON` apunta a `<dest>\fake-mysql\venv`, cuyo `pymysql` escribe en `logs.db` (sqlite). Los tests usan un `pymysql` falso en `sys.modules` (`tests/test_log_db.py`).
