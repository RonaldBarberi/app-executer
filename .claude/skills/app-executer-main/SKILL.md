---
name: app-executer-main
description: Experto en la app de escritorio app-executer-main (Tkinter, src/main.py) que ejecuta, programa y monitorea los bots RPA de HDFS/projects. Úsalo para resolver bugs, implementar o cambiar funciones y responder cómo funciona cualquier parte de la app: pestañas Procesos/Actividades/Programación/Historial, entrada de ejecución (config.json/.env), diagnóstico de bots, vista de ejecución (tqdm, logs de kreton-watch, consola, filtro), scheduler CRON_DRIVER (driver de Windows, tick, runner, cola, MAX_PARALLEL, ejecuciones perdidas, pausa), historial, setup, ícono/barra de tareas, temas, idiomas EN/ES. Úsalo siempre que el usuario mencione app-executer-main, "la app", el driver, schedules.json, CRON_DRIVER, Actividades, Historial o un comportamiento de esas pantallas, aunque no nombre el skill.
---

# app-executer-main: desarrollo, bugs y preguntas

App local (solo librería estándar, Python 3.13) en `app-executer-main/`. **Todo el código está en `src/main.py`**. Tres procesos usan ese mismo archivo:

| Proceso | Cómo arranca | Qué hace |
|---|---|---|
| UI | `pythonw src\main.py` (acceso directo, `run-app-executer-main.bat`) | Clase `App` y sus pestañas. |
| Tick | Tarea de Windows `app-executer-main driver`, cada minuto: `main.py --tick` | `Scheduler.tick()`: evalúa `CRON_DRIVER`, registra *missed*, encola y lanza. |
| Runner | `main.py --run <bot> --run-id ... --trigger manual\|cron` (desacoplado) | `Scheduler.run()`: ejecuta `<venv>\Scripts\python.exe src\main.py` (`find_venv`: `venv-<bot>` o cualquier venv del bot), guarda la salida en `.out`, publica el log en el lock y escribe el resultado en el historial. |
| DB | `<python con pymysql> main.py --db test\|upload\|query --db-args <json>` (lo lanza `App.run_db` en un hilo) | `run_db_command` + `LogDatabase`: probar conexión, subir y borrar los logs de la carpeta de logs, consultar la tabla. Imprime líneas JSON. |

Todos los modos aplican los **Ajustes** del PC (`settings.json`: `WATCH_PATH` y `LOG_DB`) sobre `config.json` con `apply_settings`.

## Archivos del skill

| Archivo | Cuándo leerlo |
|---|---|
| `references/architecture.md` | Siempre antes de tocar código o responder algo no trivial: mapa de `main.py` por clase, esquemas de `state.json`, locks e `history.jsonl`, ciclo de una ejecución, UI (tema, i18n, dibujo con antialiasing), setup y driver. |
| `references/gotchas.md` | Antes de depurar o de escribir UI, scripts de PowerShell o código del scheduler. Son errores que ya pasaron. |
| `scripts/make_sandbox.py` | Para reproducir un bug o probar un cambio sin tocar la app real (ver [Sandbox](#sandbox-nunca-pruebes-sobre-lo-real)). |
| `../../../docs/manual/` | Manual de usuario por pestaña. Es la fuente para preguntas de "cómo se usa X"; actualízalo si cambias un comportamiento visible. |
| `../../../README.md` | Instalación, configuración y estructura. |

Ubica el código con `Grep` por nombre de clase o método (`^class RunView`, `def tick`). No confíes en números de línea: cambian.

## Reglas del proyecto (del usuario y del equipo)

- Responde en español, conciso. Empieza con "KretoN". El código, los comentarios y los commits van en inglés.
- **Propón antes de editar** cambios grandes o no pedidos, y espera la aprobación. No hagas commit ni push, ni borres archivos, sin confirmación. Para modificar archivos usa la herramienta de edición, no `sed` ni `echo >`.
- **Haz solo lo pedido.** Si ves otros problemas, menciónalos sin corregirlos.
- Solo librería estándar: `requirements.txt` está vacío a propósito. Pillow existe en otros venvs, solo para capturas de pantalla, nunca como dependencia.
- **`src/` plano:** no crees módulos nuevos; todo va en `src/main.py`, en la sección correspondiente.
- Lo configurable va en `config/config.json` y se lee desde `App`/`Scheduler`. Los textos van en `config/i18n.json`, **siempre en `en` y `es`** (`tests/test_i18n.py` lo exige).
- No rompas la UI: los colores salen de `app.colors[...]` y se registran con `app.register(widget, fn)`. Las formas redondeadas o circulares se dibujan con `aa_round_rect`, `aa_circle` o `draw_icon`, nunca con `create_oval`/`create_polygon`, porque Tk no aplica antialiasing. Todo recuadro va redondeado: tarjetas con `app.card`, cajas tintadas con `app.soft_box`, campos con `themed_entry` y combos con `themed_combobox` (nunca `tk.Entry`/`ttk.Combobox` sueltos).
- Los errores que ve el usuario se lanzan con `LocalizedError('clave.i18n', **params)` y se muestran con `app.error_text(err)`.
- Después de editar, corre los tests:
  ```powershell
  cd C:\Users\re.barberi\HDFS\projects\app-executer-main
  .\venv-app-executer-main\Scripts\python.exe -m unittest discover -s tests -v
  ```

## Flujo según la tarea

### 1. Pregunta ("¿cómo funciona X?", "¿por qué pasa Y?")

1. Busca la respuesta en `docs/manual/` (comportamiento visible) y en `references/architecture.md` (por dentro).
2. Confírmala en `src/main.py` con `Grep`/`Read`. La respuesta tiene que reflejar el código actual, no la memoria. Cita `src/main.py` con el nombre de la clase o el método.
3. Si depende del estado real (qué corre, último tick, historial), léelo **en modo solo lectura** desde `%LOCALAPPDATA%\app-executer-main\scheduler\` o con `Scheduler(base, config)` (`running()`, `read_state()`, `history()`, `driver_status()`). No escribas ahí.

### 2. Bug

1. **Reprodúcelo en un sandbox** (`scripts/make_sandbox.py`) con bots demo, o en un test unitario si es lógica pura (cron, tick, `ProjectConfig`, parsers). Para la UI, abre `App` del sandbox desde un script, maneja la interfaz con `app.root.update()` y toma capturas (ver gotchas).
2. Revisa `driver.log` (errores del tick y del runner, que corren sin consola) y los archivos de estado del sandbox.
3. Antes de culpar a la app, descarta el entorno de la prueba. Ya pasó: bots demo que escribían en una carpeta distinta de `WATCH_PATH`, o un docstring que mencionaba `pi_kreton_rpa` y activó el diagnóstico.
4. Explica la causa y propone el arreglo. Edita solo después de la aprobación.
5. Agrega un test que falle sin el arreglo, cuando sea posible, y vuelve a validar en el sandbox.

### 3. Función nueva o cambio

1. Lee `references/architecture.md` y ubica dónde va: qué página o clase, si es UI, scheduler o setup.
2. Propone un plan corto: qué cambia, dónde, claves nuevas de config o i18n y qué se prueba. Espera la aprobación.
3. Implementa respetando las reglas anteriores.
4. Valida:
   - [ ] Tests unitarios en verde (agrega tests si es lógica).
   - [ ] Sandbox: el flujo funciona y las capturas se ven bien en **claro y oscuro** y en **en y es**.
   - [ ] Si toca el scheduler: prueba `--tick` y `--run` reales en el sandbox. Si toca el driver: instala el del sandbox con `-NoShortcut` y desinstálalo con `-RemoveScheduler` al final.
   - [ ] Actualiza `README.md` y el manual de la pestaña afectada en `docs/manual/`.
5. Resume qué cambió, cómo se probó y qué quedó pendiente. No hagas commit hasta que te lo pidan.

## Sandbox: nunca pruebes sobre lo real

La app real tiene estado vivo: el driver ejecuta cada minuto, `config/schedules.json` es compartido y los bots reales envían correos y escriben en SQL de producción. Por eso:

- **Nunca** lances bots reales, ni edites `schedules.json` o archivos `.env`/`config.json` de bots, para probar.
- **Nunca** subas logs a la base real ni ejecutes `--db upload` fuera del sandbox: borra los logs de la carpeta. La base real (`bbdd_data_vault`) es del usuario; para leerla, aunque sea con `--db test`, pide autorización. El sandbox trae su propio MySQL falso.
- **Nunca** escribas en `%LOCALAPPDATA%\app-executer-main\` ni reinstales o borres el driver real, salvo que el usuario lo pida.
- Usa el sandbox:
  ```powershell
  .\venv-app-executer-main\Scripts\python.exe .claude\skills\app-executer-main\scripts\make_sandbox.py --dest <carpeta del scratchpad>
  ```
  El script crea `<dest>\projects\app-executer-main` (copia de `src/` y `config/` con `APP_NAME = app-executer-main-sandbox`, de modo que tiene su propio estado, preferencias y tarea de driver), los bots demo `rpa-bot-demo-ventas` (tqdm, termina bien), `rpa-bot-demo-sap` (error de Selenium aplanado más traceback, sale con 1) y `rpa-bot-demo-sin-venv`, `<dest>\kreton-watch` (logs), `<dest>\common\.env` (credenciales falsas) y `<dest>\fake-mysql` (venv con un `pymysql` falso que escribe en `logs.db`, sqlite; es el `LOG_DB.PYTHON` de la copia). Imprime cómo abrir la UI, ejecutar un tick o instalar el driver del sandbox.
- Las capturas de pantalla se toman con Pillow desde otro venv que lo tenga, por ejemplo `..\rpa-bot-agent-abnormal-inventory\venv-...\Scripts\python.exe`. Ver gotchas.
