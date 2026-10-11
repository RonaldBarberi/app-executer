# app-executer-main

App de escritorio local (Tkinter, solo librería estándar) para lanzar los procesos RPA de `HDFS/projects/` y seguirlos en vivo.

**Manual de uso por pestaña:** [docs/manual](docs/manual/README.md), que cubre [Procesos](docs/manual/01-procesos/README.md), [Actividades](docs/manual/02-actividades/README.md), [Programación](docs/manual/03-programacion/README.md), [Historial](docs/manual/04-historial/README.md) y [Ajustes](docs/manual/05-ajustes/README.md).

## Instalación (también en otro PC)

1. Copia la carpeta `app-executer-main` dentro de `HDFS/projects/`, junto a los bots. Así, `../../kreton-watch` apunta a la carpeta de logs. Si en ese PC los logs están en otra carpeta, cámbiala en **Ajustes**.
2. Ejecuta **`setup-app-executer-main.bat`** con doble clic. El script:
   - Valida que estén Python 3.13 y tkinter. Si faltan, explica cómo instalarlos.
   - Crea `venv-app-executer-main`, o lo regenera si se copió de otro PC y ya no funciona.
   - Instala `requirements.txt`, solo si tiene dependencias; hoy no tiene ninguna.
   - Verifica que existan las carpetas de los bots y de logs (la de `config.json`; los Ajustes de cada PC no los revisa).
   - Crea el acceso directo **app-executer-main** en el menú Inicio, con el ícono de KretoN y el `APP_ID` de la app. Con `setup-app-executer-main.bat -Desktop` también crea uno en el escritorio.
   - Instala el **driver del scheduler**: la tarea de Windows `app-executer-main driver`, que ejecuta `pythonw src\main.py --tick` cada minuto. Ver [Scheduler](#scheduler-cron_driver).
   - Opciones: `-NoShortcut` (sin acceso directo), `-NoScheduler` (sin driver: este PC no ejecuta horarios) y `-RemoveScheduler` (solo desinstala el driver).
3. Para anclarla: menú Inicio → busca `app-executer-main` → clic derecho → **Anclar a la barra de tareas**. Windows no permite anclarla desde un script.

Si mueves la carpeta, vuelve a ejecutar el setup: el acceso directo guarda la ruta absoluta.

¿Por qué no anclar el `.bat`? Windows no deja anclar archivos `.bat`. Además, el acceso directo lleva el mismo `APP_ID` que la app fija al arrancar; sin él, la ventana abierta aparecería como un segundo botón al lado del anclado.

## Uso

Desde el menú Inicio (o la barra de tareas, si la anclaste), o con:

```powershell
.\run-app-executer-main.bat
```

- **Ventana principal**, con cuatro pestañas:
  - **Processes / Procesos:** todas las carpetas de `projects/`. Para ejecutar uno, haz doble clic o usa **Start execution / Iniciar ejecución** en su fila. La fila muestra si el bot está corriendo, en cola o cómo terminó su última ejecución.
  - **Activities / Actividades (n):**
    - A la izquierda, los bots en ejecución, en cola y los que terminaron mientras la app estaba abierta (**Quitar terminadas** los saca de la lista).
    - A la derecha, la vista de la ejecución seleccionada: progreso, eventos de log, consola, duración y **Detener**.
    - Una ejecución en cola muestra **Cancelar ejecución en cola**. No se abren ventanas aparte.
  - **Scheduled / Programación:**
    - Estado del driver (activo, no instalado, deshabilitado o apuntando a otra copia), último tick y PC, con **Pausar/Reanudar en este PC** e **Instalar driver**.
    - Tabla de horarios: bot, `CRON_DRIVER` en texto legible (una fila por expresión), próxima ejecución, última ejecución y si está activo.
    - Botones: **Nuevo horario**, **Editar** (o doble clic), **Activar/desactivar**, **Iniciar ahora** y **Eliminar**.
    - El editor admite varias expresiones por bot, atajos (cada 15 min, cada hora, diario 08:00, días hábiles 08:00), validación en vivo con la descripción y las próximas ejecuciones.
  - **History / Historial:**
    - Todas las ejecuciones (manuales y programadas) y los avisos *Missed* (perdida) y *Queued* (en cola).
    - Filtros por bot, estado y texto.
    - Doble clic abre la ejecución con sus logs y su consola; **← Historial** vuelve a la lista.
    - **Subir logs a la BD:** sube a MySQL todos los logs terminados de la carpeta de logs y los borra de la carpeta. Pide confirmación, no toca los logs de bots en ejecución y muestra el resumen. Ver [Base de datos de logs](#base-de-datos-de-logs).
    - **Logs del servidor:** consulta los logs ya subidos, con filtros por proceso, nivel, texto y fechas, y el mensaje completo de la fila seleccionada.
  - **Ajustes** (cabecera): carpeta de logs y base de datos de logs de este PC.
  - El ícono de luna o sol cambia el tema, **EN/ES** cambia el idioma y ↻ vuelve a leer la lista de procesos.
- **Idioma:** inglés por defecto y español. El botón **EN/ES** de la cabecera cambia el idioma en vivo, incluidas las ventanas de ejecución abiertas, y se recuerda por usuario en `%LOCALAPPDATA%\app-executer-main\settings.json`. Los textos están en `config/i18n.json` y siguen la terminología de la consola de AWS (CloudWatch Logs, Step Functions). Los mensajes que escribe el bot en su log no se traducen.
- **Diagnóstico:** los bots con problemas muestran un ícono junto a su estado. Al hacer clic se abre un popup que explica el motivo y, cuando aplica, trae un comando listo para copiar.
  - `!` rojo: el bot no se puede ejecutar desde la app. Pasa cuando falta `src/`, `src/` está vacía, no hay `src/main.py`, no tiene entorno virtual o falta `pi_kreton_rpa` en el venv.
  - `i` ámbar: el bot se puede ejecutar, pero con avisos. Por ejemplo, `stream_output=False` (no habrá barra de progreso) o que no se encontró `GROUP_LOG`.
- **Entrada de ejecución (Execution input):** al iniciar una ejecución se abre primero una tabla con todas las claves de los archivos que carga el `Pipeline` del bot. Los archivos se leen de `filename_args_json` y `filename_args_env` en su `main.py`; normalmente son `config/config.json`, `common/.env` y `config/.env`.
  - Doble clic en un valor para editarlo. Las listas y los objetos se editan en un editor JSON, que valida el formato.
  - Las claves que otro archivo reemplaza aparecen en gris, igual que en el `Pipeline`, donde `.env` gana sobre `config.json`.
  - Los valores con nombre de secreto (PASSWORD, TOKEN, KEY…) se muestran enmascarados; el botón **Show values / Mostrar valores** los revela.
  - **Save and start execution / Guardar e iniciar ejecución:** si hay cambios, pide confirmación (con advertencia si toca `common/.env`, que es compartido por todos los bots), los **guarda en el archivo** y lanza el bot. **Cancelar** no guarda nada ni ejecuta.
  - Solo se reescribe el valor editado; el resto del archivo (formato, comentarios, comillas) queda intacto. Si el archivo cambió en disco mientras lo editabas, no se guarda.
- **Vista de ejecución** (en Activities y en History; puedes correr varios bots a la vez): todo se lee de archivos: la salida de consola de `runs/<bot>/<run_id>.out` y los eventos del log del bot en la carpeta de logs. Por eso la misma vista sirve para una ejecución en curso, una que lanzó el driver o una ya terminada. La ejecución corre **en segundo plano** (runner desacoplado): cerrar la ventana o la app no detiene el bot, y al reabrir la app aparece como *Running*, con **View execution** para engancharse. Cada ventana muestra:
  - Barra de progreso tqdm del job actual (`desc`, `n/total`, `%`).
  - **Log events / Eventos de registro:** tabla al estilo CloudWatch con las columnas **Timestamp | Message** (Marca temporal | Mensaje), leída en vivo de `<carpeta de logs>/<GROUP_LOG>/<run_id>.txt`. El nivel va al inicio del mensaje (`[ERROR] ...`). No hay ajuste de línea: los mensajes largos se recorren con la barra horizontal o con Shift + rueda. Las filas WARNING salen en ámbar, las ERROR en rojo y la salida de consola que no viene de tqdm en gris.
  - **Errores aplanados en el log:** `log._sanitize` de `pi_kreton_rpa` reemplaza los saltos de línea por espacios. La app los reconstruye en `(Session info:`, `For documentation…`, `Stacktrace:`, en cada frame `módulo!función [0x…]` y, en tracebacks de Python, en cada `File "…", line N` y en la excepción final. La fila muestra la primera línea y "(+N líneas, expande con ▶)"; en un traceback muestra la excepción.
  - **Eventos de varias líneas:** un traceback de consola llega línea por línea. Las líneas con sangría, y la línea final de la excepción, se agrupan en un solo evento que se muestra en una sola fila. Se despliega con ▶ o con doble clic para ver una línea por fila, como en CloudWatch.
  - **Copiar:** clic derecho sobre una fila abre el menú **Copy message** (solo el mensaje; un traceback se copia con sus saltos de línea originales), **Copy event** (marca temporal y mensaje, separados por tabulación; también con Ctrl+C) y **Select all** (Ctrl+A). Funciona con varias filas seleccionadas y con líneas sueltas de un evento desplegado.
  - **Filter events / Filtrar eventos:** si escribes un nivel (`ERROR`, `WARNING` o `WARN`, `INFO`) se muestran solo los eventos de ese nivel. Cualquier otro texto se busca en la marca temporal y el mensaje, sin distinguir mayúsculas (por ejemplo `HA_1`, `celulares`, `08:39`). El contador muestra "N of M events" y Esc limpia el filtro. Los eventos que llegan mientras hay un filtro activo solo aparecen si coinciden.
  - Duración y estado final: Succeeded / Correcto, Failed (exit code n) / Error (código de salida n) o Aborted / Anulado.
  - **Stop execution / Detener ejecución:** mata el proceso y todos sus hijos (`taskkill /T /F`): jobs, Chrome, etc.
- Un mismo proyecto no se puede ejecutar dos veces al tiempo. Si ya está corriendo, **Start execution** abre su vista. Las ejecuciones manuales y las programadas comparten `MAX_PARALLEL`: si no hay cupo, la ejecución queda en cola (aviso *Execution queued*) y arranca sola cuando se libera uno.

## Cómo funciona

- Cada ejecución (manual o programada) la hace el runner `main.py --run <bot>`. El runner lanza `<venv>\Scripts\python.exe src\main.py` directamente (usa `venv-<proyecto>` si existe; si no, cualquier carpeta del proyecto que sea un venv, es decir, con `pyvenv.cfg` y `Scripts\python.exe`, como `.venv` o `venv`), sin pasar por el `.bat`, que pausa si el proceso falla. No se abre ninguna consola.
- `GROUP_LOG` se lee del `main.py` (`GROUP_LOG = '...'` o `log.set_group('...')`). Si no aparece, se usa el nombre de la carpeta.
- La barra tqdm solo se ve en los proyectos con `Pipeline(..., stream_output=True)`. Con `False` (hoy `rpa-bot-psi-falabella` y `rpa-bot-psi-cenco`) el stderr de los jobs queda capturado, así que solo se ven los logs y el tiempo.

## Scheduler (CRON_DRIVER)

Los horarios se administran en la pestaña **Scheduled / Programación**. También se puede editar `config/schedules.json` a mano.

- **Definición:** `config/schedules.json`, compartido con la app y versionado en git. Cada bot tiene una lista de expresiones cron estándar de 5 campos en `CRON_DRIVER` y un `ENABLED`:
  ```json
  {"rpa-bot-d2c-dashboard": {"CRON_DRIVER": ["0 6-22/2 * * 1-5"], "ENABLED": true}}
  ```
  Sintaxis admitida: `*`, rangos, listas, pasos, `JAN`–`DEC`, `SUN`–`SAT` (7 también es domingo) y `@hourly`/`@daily`/`@weekly`/`@monthly`/`@yearly`. Si se restringen el día del mes y el día de la semana, basta con que se cumpla uno de los dos, como en Vixie cron.
- **Driver:** la tarea `app-executer-main driver` ejecuta `main.py --tick` cada minuto mientras tu sesión de Windows esté iniciada. Sirve también con la **pantalla bloqueada (Win+L) o el PC desatendido**. No corre si nadie inició sesión (por ejemplo, después de reiniciar). Esto es a propósito: `pi_kreton_rpa` envía los correos con Outlook por COM y lee los archivos NASCA con Excel por COM, y los dos necesitan el escritorio del usuario. En una tarea "con o sin sesión" (sesión 0) fallarían. Por eso: no cierres sesión, bloquea el PC. Después de un reinicio, inicia sesión para que vuelva a ejecutar. El tick lanza cada bot vencido con `main.py --run <bot>`, un *runner* desacoplado que:
  - guarda la salida en un archivo,
  - registra la ejecución en el historial,
  - sigue vivo aunque se cierre la app.
- **Reglas:**
  - Si el bot ya está corriendo, o se llegó a `MAX_PARALLEL` bots a la vez, la ejecución se encola (máximo una por bot). La arranca el runner que termina.
  - Una ejecución con más de `MISSED_AFTER_MINUTES` de retraso (PC apagado, suspendido o sin sesión) no se recupera: queda en el historial como *missed*.
- ⚠️ **Varios PCs:** `schedules.json` viaja con la app. Cada PC con el driver instalado ejecuta esos horarios, así que dos PCs duplicarían las ejecuciones. En los PCs que no deben ejecutar, instala con `-NoScheduler` o desinstala con `-RemoveScheduler`.
- **Estado por PC** en `%LOCALAPPDATA%\app-executer-main\scheduler\`:
  - `state.json`: último tick, cola y pausa en este PC.
  - `locks\<bot>.json`
  - `runs\<bot>\<run_id>.out`: stdout y stderr del bot.
  - `history.jsonl`
  - `driver.log`: errores del tick o del runner, que corren sin consola.
  - Se conservan `HISTORY_DAYS` días.
- **Tareas existentes:** si un bot ya se programa con el Programador de tareas de Windows, desactiva esa tarea al pasarlo a `CRON_DRIVER`; si no, corre dos veces.

## Base de datos de logs

**Historial → Subir logs a la BD** sube los logs de la carpeta de logs a MySQL; **Logs del servidor** los consulta. Se configura en **Ajustes** ([manual](docs/manual/05-ajustes/README.md)).

- **Sin dependencias en la app:** la app sigue siendo solo librería estándar. La subida y las consultas corren en otro proceso, `main.py --db test|upload|query`, con un Python que tenga `pymysql`. Puede ser el elegido en Ajustes o, si está vacío, el primer venv de `projects/` que lo tenga. Ese proceso imprime líneas JSON (avance y resultado) que la app lee.
- **Credenciales:** se leen del `.env` elegido (por defecto `HDFS/common/.env`), con las variables `OWNER_SQL_HOST`, `OWNER_SQL_PORT`, `OWNER_SQL_USER` y `OWNER_SQL_PASSWORD` (`LOG_DB.ENV_KEYS`). La app nunca las guarda.
- **Tabla:** `bbdd_data_vault.tb_logs_watch_bots`, con las columnas `id` (autoincremental), `process_name` (GROUP_LOG), `id_process` (run_id), `timestamp_log`, `type_log`, `message` y `update_at` (hora de la subida). Cada línea del log es una fila; una línea sin formato, como la continuación de un traceback, se une al mensaje anterior.
- **Subida segura:**
  - Cada archivo se sube en una transacción y solo se borra si se confirmó.
  - Antes de insertar se borran las filas de la misma ejecución (`process_name` + `id_process`), así que reintentar no duplica.
  - Se omiten los logs de ejecuciones en curso (los locks del scheduler) y los que otro proceso tiene abiertos. Antes de subir un archivo se renombra a `.uploading`; si el bot lo tiene abierto, Windows no deja renombrarlo.
  - Un `.uploading` que quedó de una subida interrumpida se retoma en la siguiente.
  - Las carpetas de grupo que quedan vacías se borran.

## Configuración (`config/config.json`)

Los **Ajustes** de cada PC (`%LOCALAPPDATA%\app-executer-main\settings.json`) reemplazan `WATCH_PATH` y los campos `PYTHON`, `ENV_FILE`, `DATABASE` y `TABLE` de `LOG_DB`. Los aplican la UI, el tick, el runner y `--db`.

| Clave | Uso |
|---|---|
| `PROJECTS_PATH` / `WATCH_PATH` | Rutas relativas a la raíz de la app: `projects/` (`..`) y la carpeta de logs (`../../kreton-watch`). |
| `LOG_DB` | Base de datos de logs: `PYTHON` (Python con pymysql; vacío = detectar), `ENV_FILE` (`../../common/.env`), `ENV_KEYS` (nombres de las variables), `DATABASE`, `TABLE` y `QUERY_LIMIT` (filas máximas de **Logs del servidor**, 1000). |
| `EXCLUDED_PROJECTS` | Carpetas que no se listan. |
| `POLL_MS`, `MAX_LOG_LINES` | Frecuencia de refresco (ms) y máximo de líneas de log por ventana. |
| `THEME_DEFAULT`, `THEMES` | Tema inicial y paleta de colores de KretoN (claro: acento teal `#225866`; oscuro: fondo teal profundo y acento amarillo `#F2BB30`). |
| `I18N_FILE`, `LANGUAGE_DEFAULT` | Archivo de textos por idioma (`en`, `es`) e idioma inicial (`en`). Una clave que falte en `es` se muestra en inglés; `tests/test_i18n.py` valida que ambos idiomas tengan las mismas claves y placeholders. |
| `ASSETS_PATH`, `ICON_FILE` | `kreton.ico` es el logo de KretoN (tamaños de 16 a 256 px). Se usa en la barra de tareas, en la barra de título y en el acceso directo. `logo-<n>.png` es el logo de la cabecera, con esquinas redondeadas transparentes. |
| `SCHEDULES_FILE`, `MAX_PARALLEL`, `MISSED_AFTER_MINUTES`, `HISTORY_DAYS` | Scheduler: archivo de horarios (`config/schedules.json`), bots en paralelo (2), minutos de retraso tras los cuales una ejecución cuenta como perdida (5) y días de historial (30). |
| `APP_ID` | AppUserModelID de Windows. Hace que la barra de tareas muestre el logo propio y no el de Python. |

## Tests

```powershell
.\venv-app-executer-main\Scripts\python.exe -m unittest discover -s tests -v
```

| Archivo | Cubre |
|---|---|
| `test_cron.py` | Parser `CronExpression`: rangos, pasos, nombres, día de mes o día de semana, 29 FEB y 30 FEB, errores, descripción en/es |
| `test_scheduler.py` | Tick (con un reloj simulado), *missed*, cola por bot ocupado y por `MAX_PARALLEL`, drenado de la cola, pausa, horarios inválidos, solicitud manual, locks huérfanos, historial, limpieza y conflicto al guardar `schedules.json` |
| `test_config.py` | Lectura y escritura de `config.json` y `.env` sin alterar el formato |
| `test_parsers.py` | tqdm, líneas del log de los bots, filtro de eventos, tracebacks y errores aplanados |
| `test_log_db.py` | Base de datos de logs, con un `pymysql` falso sobre sqlite: parser del log, Ajustes por PC, `.env` (variables que faltan, puerto, nombres), detección del Python con pymysql, subida y borrado, logs en ejecución o abiertos que se omiten, archivo con error que se deshace y se conserva, reintento sin duplicar, `.uploading` retomado y filtros de la consulta |
| `test_venv.py` | `find_venv`: prefiere `venv-<bot>`, acepta un venv con cualquier nombre, ignora carpetas sin `pyvenv.cfg` |
| `test_i18n.py` | Mismas claves y placeholders en en/es, y que existan las claves que usa el código |

**Prueba con el driver real** (hecha en una copia aislada, con su propio `APP_NAME`, su estado y bots falsos), para repetirla al cambiar el scheduler:
1. Ejecuta el setup de la copia con `-NoShortcut` y programa dos bots con `* * * * *` y `MAX_PARALLEL=1`. Esperado: Activities muestra uno *Running* y otro *Queued*, y la cola arranca sola.
2. Pon en `state.json` un `last_tick` de hace 30 minutos. Esperado: un aviso *Missed (n)* por bot y ninguna ejecución de esos horarios.
3. Activa **Pausar en este PC**. Esperado: `last_tick` sigue avanzando, sin ejecuciones nuevas.
4. Al final, ejecuta el setup de la copia con `-RemoveScheduler` y revisa que no queden locks ni cola, y que `driver.log` no tenga errores.
