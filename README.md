# busqueda-corolla: monitoreo diario de Toyota Corolla 2022–2026 en Carroya

**Taller 2, Taller de Python (Uniandes).** Workflow en Python que, cada día del 16 al 21 de noviembre de 2026:
1. Consulta los anuncios de Toyota Corolla modelo 2022–2026 en Carroya.
2. Descarga cada anuncio.
3. Consolida la información en una base SQLite.
4. Registra cada etapa en un log.
5. Analiza los precios para detectar posibles gangas.
6. Envía un correo diario con los resultados.

Todo corre en **GitHub Actions**; no hace falta ningún computador encendido.

---

## 1. Cómo funciona

```
 GitHub Actions · diario.yml (8:00)                                     GitHub Actions · correo.yml (11:00)
 ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌─────────┐      ┌────────────────────┐
 │ Búsqueda │ → │ Descarga │ → │ Consolidación│ → │ Análisis │ → │ commit  │ ···> │ Correo (Gmail SMTP)│
 │ API      │   │ detalle  │   │ SQLite       │   │ gangas   │   │ al repo │      │ lee log y reportes │
 └──────────┘   └──────────┘   └──────────────┘   └──────────┘   └─────────┘      └────────────────────┘
       └──────────────── cada etapa escribe una fila en logs/log_ejecuciones.csv ────────────────┘
```

**El servicio en GitHub.** El repositorio contiene a la vez el código, la programación de las tareas y los datos. En cada ejecución, GitHub Actions hace lo siguiente:
1. Enciende una máquina Ubuntu temporal.
2. Descarga el repositorio, que trae los datos acumulados de los días anteriores.
3. Instala las dependencias.
4. Ejecuta el pipeline.
5. Hace **commit y push** de los archivos nuevos. Ese commit es lo que conserva el historial de un día al siguiente.
6. Se apaga.

La contraseña de Gmail es un *secret* del repositorio (`GMAIL_APP_PASSWORD`): no está en el código ni aparece en los logs. Cada ejecución queda registrada en la pestaña **Actions**, con su hora real, y en un commit con fecha.

**Fuente de datos.** La página de Carroya se arma con JavaScript, pero sus datos vienen de una API pública:
- `POST https://carroya-habilitadora-api.avaldigitallabs.com/find-filters` devuelve la búsqueda paginada: 20 anuncios por página, junto con `count` y `pages`.
- `GET https://carroya-habilitadora-api.avaldigitallabs.com/find-vehicle-detail/{uuid}` devuelve el detalle de cada anuncio.

Por eso no se usa Selenium ni se lee HTML.

## 2. Estructura del repositorio

```
src/corolla/
  config.py       rutas, zona horaria (America/Bogota), criterios de búsqueda
  recolectar.py   paso 1: búsqueda paginada, verificación de criterios, descarga, archivos diarios
  consolidar.py   pasos 2 y 3: base SQLite y actualización idempotente
  analizar.py     paso 6: distribución de precios, gangas, posibles duplicados
  correo.py       paso 7: plantilla HTML y envío
  logs.py         paso 5: log por etapa
  pipeline.py     orquestación de las 8:00
tests/            11 pruebas automáticas sin internet (API simulada)
datos/diarios/AAAA-MM-DD/   enlaces_AAAA-MM-DD.csv · datos_AAAA-MM-DD.csv · busqueda_AAAA-MM-DD.json
datos/corolla.db  base consolidada
datos/export/     las 4 tablas de la base en CSV
reportes/AAAA-MM-DD/  resumen.json · distribucion.png · evaluacion.csv · gangas.csv · cambios_precio.csv · correo.eml/.html
logs/log_ejecuciones.csv   log consolidado del período
pruebas/          ejecuciones de prueba (9 y 15 de noviembre); nunca se mezclan con el período evaluado
docs/             notebook del diseño, documento de una página (Documento_Taller2.pdf) y su generador
correos/          los 6 correos del período (.eml con fecha y hora; PDF exportado del buzón)
.github/workflows/ diario.yml · correo.yml · sonda.yml (prueba inicial de conectividad)
```

## 3. Cómo ejecutarlo

```bash
pip install -r requirements.txt
export PYTHONPATH=src

python -m pytest                                    # pruebas (no necesitan internet)
python -m corolla.pipeline --modo prueba            # recolección + consolidación + análisis -> pruebas/
python -m corolla.correo   --modo prueba            # arma el correo (y lo envía si hay credenciales)
```

- `--modo real` escribe en `datos/`, `logs/` y `reportes/`. `--modo prueba` escribe todo en `pruebas/` y pone **[PRUEBA]** en el asunto del correo.
- `--fecha AAAA-MM-DD` reprocesa un día. `--esperar-hasta HH:MM` espera hasta esa hora de Bogotá. `--una-vez` omite la ejecución si ese día ya se hizo.
- **Para enviar el correo** se necesitan las variables `GMAIL_USER`, `GMAIL_APP_PASSWORD` (una contraseña de aplicación de Google) y `COROLLA_DESTINO`. En GitHub, la contraseña va en *Settings → Secrets and variables → Actions*.
- **En GitHub:** pestaña *Actions* → elegir el workflow → *Run workflow*. El campo `modo` acepta `prueba`, `real` o `programado` (real, a la hora exacta y una sola vez al día).

## 4. Decisiones principales

**Identificación.** El identificador del anuncio es el **UUID de Carroya** (por ejemplo `d1bf9d95-155f-4610-ab51-e93207c59ff7`). Es estable entre días y forma parte de la URL, así que volver a encontrar una publicación nunca crea un anuncio nuevo.

**Mismo vehículo en varios anuncios.** Se marca como *posible duplicado* cuando coinciden año, versión, color y ciudad, y el kilometraje difiere menos de 2 %. Solo se reporta, no se fusiona. Por ejemplo, dos anuncios de un Corolla 2025 con 14.000 km y $116,9 M en Medellín. Limitación: sin la placa completa puede haber falsos positivos.

**Archivos diarios.** Ambos archivos tienen los estados `sin intentar`, `descargado` y `fallido`, con el motivo del error. Un anuncio *sin intentar* tiene la hora del intento vacía. El archivo de datos incluye los fallidos con los campos del vehículo vacíos. Un dato faltante queda vacío: nunca se inventa ni se convierte en 0. La API usa "0" para una transmisión vacía y se trata como faltante. El sunroof es `si` o `no` según los accesorios, y queda vacío si el anuncio no trae lista de accesorios. **No se guardan datos del vendedor** (nombre, correo, dirección, placa): se usa una lista blanca de campos.

**Almacenamiento: SQLite**, con 4 tablas:

| Tabla | Llave | Contenido |
|---|---|---|
| `anuncios` | id_anuncio | ficha más reciente, `primera_vez_visto`, `ultima_vez_visto`, `disponibilidad_actual` |
| `observaciones` | (id_anuncio, fecha) | una fila por anuncio y día: disponibilidad, estado y hora de la descarga, valores del día |
| `cambios` | (id_anuncio, fecha, campo) | valor anterior → valor nuevo |
| `archivos_procesados` | sha256 | archivos diarios ya incorporados |

| | **SQLite (elegida)** | CSV | Parquet |
|---|---|---|---|
| Consultas y cruces | SQL completo | cargar todo en pandas | pandas o duckdb |
| Evitar duplicados | PRIMARY KEY + UPSERT | a mano | a mano |
| Varias tablas relacionadas | un solo archivo | un archivo por tabla | un archivo por tabla |
| Abrir sin programar | requiere DB Browser | Excel | no |
| Diferencias legibles en git | no (binario) | sí | no (binario) |

Para compensar las dos desventajas, cada día se exportan las tablas a `datos/export/*.csv`.

**Actualización idempotente.**
- Si la huella sha256 de un archivo ya está registrada, el archivo no se vuelve a procesar.
- Las observaciones se escriben con UPSERT por (id, fecha).
- Los cambios se calculan contra la última observación *descargada* anterior.
- La ficha de cada anuncio se recalcula a partir de las observaciones, así que el resultado no depende del orden en que se procesen los días.

**Disponibilidad:**

| Situación | Disponibilidad |
|---|---|
| Apareció en la búsqueda, aunque falle la descarga del detalle | `encontrado` |
| No apareció y la búsqueda fue completa (todas las páginas y `count` cuadra) | `no_encontrado`, que **no** significa vendido |
| No apareció y la búsqueda quedó incompleta | `desconocido` |

**Logs.** Una fila por etapa y ejecución con: id de ejecución, etapa, inicio, fin, duración, estado, enlaces, anuncios nuevos, descargas exitosas, fallidas y pendientes, registros agregados, actualizados y sin cambio, anuncios únicos, tamaño de la base, búsqueda completa, errores y estado del correo. Todas las horas van en **America/Bogota con el desfase explícito** (`-05:00`).

**Gangas: método de comparables con jerarquía.**
- **Distribución diaria:** una observación por anuncio, la descargada ese día con precio válido. Un precio es inválido si falta, si es menor de $20 M o mayor de $400 M, o si no está en pesos.
- **Grupo de referencia:** para cada anuncio se busca el grupo más específico que tenga **al menos 5 comparables**:
  1. mismo año + mismo combustible + misma banda de kilometraje;
  2. mismo año + mismo combustible;
  3. año ±1 + mismo combustible.

  Si ninguno alcanza, el anuncio queda como "datos insuficientes" y se reporta así.
- **Regla:** posible ganga si `precio ≤ 0,85 × mediana del grupo` **y** `precio < Q1 del grupo`. Se usa la mediana porque los precios extremos no la mueven.
- **Por qué esas variables:** el año y el kilometraje son los que más explican el precio de un carro usado, y el combustible separa dos mercados distintos (unos 52 híbridos frente a unos 8 a gasolina). La versión, el sunroof y la transmisión aparecen en la explicación pero no definen el grupo, porque con unos 60 anuncios los grupos quedarían de 1 o 2 carros.
- **Cada alerta** sale con una explicación en texto: el grupo de comparación, la mediana, Q1, el porcentaje por debajo y las características del carro.
- **Solo se alertan los anuncios nuevos del día**, es decir, vistos por primera vez por el sistema.
- **Limitaciones:** el precio publicado no es el precio de venta; puede haber errores de digitación; hay pocos datos; y un duplicado puede inflar su propio grupo de referencia.

**Correo.** Plantilla HTML con:
- el estado general, leído del log de las 8:00;
- las cifras del proceso;
- los errores y las etapas pendientes;
- la gráfica y el resumen de la distribución;
- las gangas nuevas, con enlace, características, precio, referencia y explicación;
- los cambios de precio.

Se envía siempre, aunque falle parte del proceso. Si la recolección sigue en curso, el correo lo indica. Cada envío deja una copia `.eml` en `reportes/`.

## 5. Resultados del período (16 al 21 de noviembre de 2026)

| Día | Enlaces | Descargas ok / fallidas | Nuevos | Gangas nuevas | Mediana | Recolección (inicio) | Correo (envío) |
|---|---|---|---|---|---|---|---|
| 16-nov | 61 | 61 / 0 | 61 | 3 | $105,9 M | 17:30 | 18:50 |
| 17-nov | 60 | 60 / 0 | 1 | 0 | $106,4 M | 16:20 | 18:09 |
| 18-nov | 62 | 62 / 0 | 2 | 0 | $106,4 M | 15:53 | 17:41 |
| 19-nov | 61 | 61 / 0 | 0 | 0 | $106,9 M | 15:58 | 17:45 |
| 20-nov | 61 | 61 / 0 | 0 | 0 | $106,9 M | 15:43 | 17:21 |
| 21-nov | 61 | 61 / 0 | 0 | 0 | $106,9 M | 14:47 | 16:07 |

- **Base final:** 64 anuncios únicos (61 encontrados el último día y 3 no encontrados), 379 observaciones y 6 archivos diarios procesados.
- **Búsqueda:** completa los 6 días, sin descargas fallidas.
- **Cambios de precio:** no hubo ninguno en el período.
- **Primer día:** como todos los anuncios eran nuevos para el sistema, 3 posibles gangas. Dos de ellas son el mismo vehículo publicado dos veces (marcado como posible duplicado).

## 6. Incidencias

**Retraso del cron de GitHub Actions.** Los workflows estaban programados con `schedule` a las 7:40 y 10:40 de Bogotá; el script esperaba hasta las 8:00 y las 11:00 exactas. GitHub los arrancó **entre 6 y 10 horas tarde los seis días**: la recolección empezó entre las 14:47 y las 17:30, y el correo salió entre las 16:07 y las 18:50 (ver la tabla anterior, la pestaña Actions y `logs/log_ejecuciones.csv`). Los datos, la consolidación y los correos se completaron todos los días. Lo que no se cumplió fue la hora.

- **Causa:** GitHub no garantiza la hora de los workflows programados y los retrasa cuando sus servidores están cargados.
- **Lo que se hizo (18 de noviembre):** se agregó el modo `programado`, que espera la hora exacta y omite disparos repetidos (`--una-vez`), y se dejó un segundo cron de respaldo. Se verificó que los disparos repetidos se omiten: los días 19, 20 y 21 corrieron dos crons, y el segundo se omitió sin duplicar datos ni correos.
- **Lo que faltó:** el diseño incluía un disparador externo puntual (cron-job.org llamando a `workflow_dispatch` a las 7:55 y 10:55), pero no se configuró a tiempo.
- **Lección:** el cron de GitHub Actions sirve para tareas sin hora estricta. Con hora estricta hace falta un disparador externo o un servidor propio.

**Pruebas.** Las ejecuciones del 9 y del 15 de noviembre están en `pruebas/` y sus correos llevan [PRUEBA] en el asunto. No hacen parte de la evidencia del período.
