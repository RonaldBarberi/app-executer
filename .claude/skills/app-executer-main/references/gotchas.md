# Gotchas de app-executer-main (errores que ya pasaron)

## Tkinter y UI

- **Sin antialiasing en el Canvas:** `create_oval`, `create_polygon` y `create_line` se ven pixelados. Usa `aa_round_rect`, `aa_circle` o `draw_icon`; para un ícono nuevo, agrega un `kind` con su SDF en `draw_icon`. Los textos dentro de un círculo de color (`!`, `i`) se ven con bordes de colores por ClearType, así que se dibujan como formas.
- **`round_rect` ya no existe.** Una migración a medias dejó llamadas a una función borrada (NameError al hacer hover). Después de un refactor, busca con `Grep` los nombres viejos.
- **`Treeview.bbox(item, col)` antes de mostrar la ventana** da coordenadas falsas, y el editor en línea queda sobre el encabezado. `ConfigDialog.edit` sale si `not tree.winfo_ismapped()` y confirma la edición abierta cuando la tabla cambia de tamaño (`<Configure>`) o hace scroll.
- **El Escape del `Entry` en línea** debe devolver `'break'`; si no, también llega al `Escape` del `Toplevel` y cierra el diálogo.
- **Pack del pie:** empaca el pie con `side='bottom'` **antes** del contenido expandible; si no, el pie desaparece al achicar la ventana.
- **Lista del `TCombobox`:** se tematiza con `root.option_add('*TCombobox*Listbox.*', ...)` y solo afecta a las listas que se abren después.
- **Capturas con `ImageGrab`:** pon la ventana con `-topmost`, haz `update()` varias veces y espera unos 0,6 s. Si el usuario tiene otra ventana encima o la vista de escritorios abierta, la captura sale mal: repítela. Pillow no está en el venv de la app; usa otro venv que lo tenga.
- **Actividades y las ejecuciones terminadas:** `refresh_ui` solo redibuja la pestaña visible, pero `ActivitiesPage.track(running)` corre en cada pasada. Si el registro de las que terminan depende de que la pestaña esté abierta, las que terminan mientras el usuario mira otra pestaña nunca aparecen (ya pasó).
- **Variante de botón:** para cambiarla, asigna `button.variant` y llama `redraw()` (así se marca la pestaña activa).
- **Ícono de la barra de tareas borroso:** pasaba con `iconphoto(256 px)`. Ahora se usa `iconbitmap(default=.ico)` + `WM_SETICON` con `LoadImageW` al tamaño exacto (24 y 16 × scale) y un `.ico` con cada tamaño (16–256) guardado aparte (`kreton.ico`, reescalado con Lanczos desde el logo). Sin `SetCurrentProcessExplicitAppUserModelID` y sin el AUMID en el `.lnk`, Windows muestra el ícono de Python o separa el botón del anclado.

## Scheduler y procesos

- **`Scheduler.locked()` no es reentrante.** No llames a `request_run`, `cancel_queued`, `set_paused_here`, `stop` ni `_update_lock` dentro de otro `with self.locked()`, porque se bloquea hasta el timeout (30 s). Los métodos con prefijo `_` (`_request`, `_drain`, `_launch`, `_history_add`) asumen que quien llama ya tiene el lock.
- **`running(cleanup=True)`** borra locks y escribe historial. Úsalo solo bajo `locked()`; la UI usa `running()` sin `cleanup`.
- **El runner debe sobrevivir al tick:** el Programador de tareas ejecuta el tick dentro de un *job object*. `_spawn` usa `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB`, y si eso falla, sin breakaway. Verificado con la tarea real.
- **`pythonw` no tiene consola:** las excepciones de `--tick`/`--run` solo quedan en `driver.log`; `argparse` tampoco puede imprimir errores.
- **Reutilización de PID:** compara siempre `process_started(pid)` con el `runner_started` guardado.
- **El atraso se mide por expresión;** las ejecuciones perdidas se agrupan en un solo evento `missed` con `count`. Varias expresiones que vencen en el mismo tick dan una sola ejecución.
- **Cola:** máximo una entrada por bot (`already_queued`). La drenan el tick y cada runner al terminar.
- **"Sin sesión" no se soporta,** porque Outlook y Excel COM necesitan el escritorio. No cambies el `LogonType` del driver sin hablarlo con el usuario.

## Archivos y formatos

- **Logs de kreton-watch:** `\r\n` + `§`. El log de una ejecución es el **primero** que aparece en `kreton-watch/<GROUP_LOG>/` después de lanzar el bot. Si un bot de prueba escribe en otra carpeta (por ejemplo `watch` en vez de `kreton-watch`), la vista muestra "-": no es un bug de la app.
- **`Canvas.lift` es `tag_raise`:** para subir un canvas sobre sus hermanos usa `tk.Misc.tkraise(canvas)`. Los hijos que se crean después quedan encima de los anteriores, por eso `RoundCorners` vuelve a subir sus esquinas.
- **`themed_entry`/`themed_combobox` devuelven la caja (`RoundField`), no el input.** Empaqueta la caja y usa `.widget` para `configure(values=...)`, `current()`, etc. No le pases `ipadx` (el relleno horizontal lo pone la caja).
- **`LocalizedError(key, **params)`:** un parámetro no puede llamarse `key` (choca con el primer argumento: `TypeError: got multiple values for argument 'key'`). Usa `var`, `name`, etc.
- **Diálogos altos:** la pantalla del usuario mide 1920×1080. Un `Toplevel` que pasa de unos 950 px deja el pie (Guardar) fuera de la pantalla. Usa columnas y limita `y` con `winfo_screenheight()`, como `SettingsDialog`.
- **Python de `--db`:** carga `main.py` entero (que importa tkinter). Si ese Python no tiene tkinter, la app muestra el traceback como `db.err_generic`.
- **PowerShell 5.1 y `python -c "..."`:** quita las comillas dobles del código que se pasa como argumento. Escribe el script en un archivo del scratchpad.
- **Diagnóstico de `pi_kreton_rpa`:** es una búsqueda de texto. Un comentario o docstring que lo menciona marca el bot como "Falta pi_kreton_rpa" si no está en el venv.
- **`main.py` con BOM:** en los bots lee con `utf-8-sig`. `ProjectConfig` conserva el BOM y el CRLF al escribir.
- **No reescribas un `config.json` completo:** muchos tienen formato propio. `update_json` reemplaza solo el valor (por *spans*) y mantiene en una línea lo que estaba en una línea.
- **En una `RunView` terminada,** lee primero el log y después el `.out`, para que el traceback de consola quede al final.
- **`describe()` en español:** los nombres de días y meses salen de `cron.dow_names`/`cron.month_names` en i18n, no del locale.
- **Claves i18n armadas con f-strings** (`hist.col_*`, `hist.status_*`, `sch.col_*`, `sch.driver_*`): `test_i18n.test_keys_built_in_code_exist` las lista. Si agregas una columna o un estado, súmalo ahí.

## PowerShell (Windows PowerShell 5.1)

- No existe `&&`: usa `;` o `if ($?) {...}`.
- Con `$ErrorActionPreference = 'Stop'`, cualquier texto que un ejecutable nativo escriba en stderr se vuelve un error fatal. El setup usa `Continue` y revisa `$LASTEXITCODE`.
- **Commits con mensaje de varias líneas:** escribe el mensaje en un archivo del scratchpad y usa `git commit -F <archivo>`. Pasar un here-string a `-F -` no funciona: lo toma como pathspec.
- `git branch --show-current` no existe en esta versión de git: usa `git rev-parse --abbrev-ref HEAD`.
- **Push a `github.com`:** si falla con "Invalid username or password", hay una credencial vencida en el Administrador de credenciales (`git:https://github.com`). El usuario debe borrarla y autenticarse con un Personal Access Token; no lo reintentes en bucle.
- Un `.ps1` guardado sin BOM se lee como ANSI en PowerShell 5.1: mantén los mensajes del setup en inglés y sin tildes.
