# Guía de activación de Orbivia

Instrucciones para instalar y arrancar Orbivia en tu ordenador desde cero, con una misión simulada lista para la demo.

> Todos los datos de la demo son **simulados**. Orbivia no diagnostica ni trata enfermedades.

---

## 1. Requisitos

| Necesitas | Detalle |
|---|---|
| **Git** | Para clonar el repositorio. |
| **Docker Desktop** (macOS o Windows) o **Docker Engine + Compose v2** (Linux) | Debe funcionar `docker compose version`. Docker Desktop tiene que estar **abierto** mientras uses Orbivia. |
| **Memoria** | 8 GB de RAM como mínimo; el servicio `worker-ml` puede usar hasta 4 GB. En Docker Desktop, asigna al menos 6 GB en *Settings → Resources*. |
| **Disco** | Unos 10 GB libres para las imágenes. |
| **Conexión a internet** | Solo la primera vez, para descargar las imágenes y dependencias. |
| **Puertos libres** | 8080 (interfaz), 8000 (API), 5432 (PostgreSQL) y 6379 (Redis). Si alguno está ocupado, ver §8. |

Funciona en Mac con Apple Silicon o Intel, en Linux y en Windows con Docker Desktop (WSL 2). No hace falta instalar Python.

---

## 2. Descargar el código

```bash
git clone https://github.com/Rpa06/orbivia.git
```

```bash
cd orbivia
```

Mientras no se fusione en `develop`, la versión integrada está en la rama `integracion/orbivia-demo`:

```bash
git checkout integracion/orbivia-demo
```

**En Windows:** el repositorio ya fuerza finales de línea LF en scripts y ficheros de configuración (`.gitattributes`). Si clonaste antes de que existiera ese fichero, o la base de datos no se inicializa, desactiva la conversión y vuelve a clonar:

```bash
git config --global core.autocrlf false
```

---

## 3. Crear el fichero `.env`

El `.env` guarda las contraseñas locales. Nunca se sube a GitHub.

```bash
cp .env.example .env
```

En Windows PowerShell: `Copy-Item .env.example .env`

Abre `.env` con un editor y **cambia todos los valores que empiezan por `cambia-`**:

| Variable | Qué es |
|---|---|
| `POSTGRES_PASSWORD` | Contraseña del administrador de PostgreSQL |
| `ORBIVIA_DB_API_PASSWORD`, `ORBIVIA_DB_ENGINE_PASSWORD`, `ORBIVIA_DB_CYCLE_PASSWORD`, `ORBIVIA_DB_SYNC_PASSWORD` | Contraseñas de los roles de base de datos de cada servicio |
| `AUTH_SECRET` | Firma de las sesiones (mínimo 32 caracteres) |
| `CYCLE_ENCRYPTION_KEY` | Cifrado del registro privado del ciclo (mínimo 32 caracteres) |
| `EARTH_SYNC_TOKEN` | Token del enlace simulado con Tierra (mínimo 32 caracteres) |

Para generar valores aleatorios, ejecuta este comando una vez por cada clave y pega el resultado:

```bash
openssl rand -base64 32
```

Si no tienes `openssl`, sirve cualquier cadena larga y aleatoria de al menos 32 caracteres.

Opciones útiles del `.env`:

| Variable | Para qué |
|---|---|
| `DEMO_PASSWORD` | Si la defines, todos los usuarios de demo tendrán esa contraseña. Si la dejas vacía, se generan contraseñas aleatorias. |
| `INSTALL_NLP=false` | La imagen de `worker-ml` se construye sin PyTorch ni Transformers: ocupa menos y tarda menos. El análisis de texto está desactivado de todos modos (`ENABLE_NLP=false`). |
| `ORBIVIA_TODAY=AAAA-MM-DD` | Fija la fecha "de hoy" para que la demo no dependa del día real (ver §7). |

> Las claves de la base de datos se aplican **al crearla**. Si las cambias después, tienes que crear una base nueva (ver §8, «Empezar de cero»).

---

## 4. Arrancar Orbivia

Con Docker Desktop abierto, desde la carpeta del proyecto:

```bash
docker compose up -d --build
```

La primera vez tarda entre 10 y 20 minutos: descarga PostgreSQL y Redis, y construye las imágenes de Python. Las siguientes veces arranca en segundos.

Comprueba que todo está en marcha:

```bash
docker compose ps
```

Deben aparecer nueve servicios en estado **`healthy`**: `db`, `broker`, `media-broker`, `api`, `worker-stream`, `worker-ml`, `sync-tierra`, `earth-receiver` y `frontend`. `worker-ml` puede tardar uno o dos minutos más en pasar a `healthy`.

---

## 5. Crear la misión simulada

```bash
docker compose run --rm seed
```

Esto genera cuatro tripulantes simulados (A1-A4) con 17 días de datos, los avisos, la nota de disponibilidad y los tres planes del día. Al terminar **imprime los usuarios y contraseñas**, y los guarda también en `volumenes/demo/credenciales.txt`.

---

## 6. Entrar en la interfaz

Abre **http://127.0.0.1:8080** en el navegador e inicia sesión:

| Usuario | Rol | Qué puede hacer |
|---|---|---|
| `commander` | Comandante (y tripulante A1) | Ver la disponibilidad de la tripulación, **elegir o rechazar el plan del día**, ejecutar el colapso diario. Como tripulante: su check-in, PVT-B, entrevista, ejercicio y registro privado. |
| `astro2`, `astro3`, `astro4` | Astronautas A2-A4 | Su estado, check-in y PVT-B, entrevista de audio, ejercicio, recomendaciones, registro privado y consulta de planes. |
| `surgeon` | Médico de a bordo | Avisos y estado de toda la tripulación, gráficas, auditoría de la nota y ciclo compartido. |
| `earth.medical` | Equipo médico en Tierra | Historial de cada tripulante. |
| `earth.mission` | Misión en Tierra | Solo datos agregados; grafo de cohesión si hay una incidencia social. |

Guion corto de demo:

1. Entra como **`surgeon`**: avisos visuales de la tripulación, gráficas con su banda de referencia y radiación.
2. Entra como **`astro3`** y haz el check-in y el PVT-B. Para que el PVT-B dure 30 s en lugar de 3 minutos, abre http://127.0.0.1:8080/?pvt30
3. Entra como **`commander`**: pulsa **«↻ Ejecutar colapso diario»**, revisa la disponibilidad y **elige uno de los tres planes**.
4. Entra como **`astro4`**: registro privado del ciclo, con la opción de compartirlo 24 h con el médico.
5. Entra como **`earth.mission`**: estado agregado y grafo de cohesión.

---

## 7. Uso diario

| Quiero… | Comando |
|---|---|
| Parar Orbivia (los datos se conservan) | `docker compose stop` |
| Volver a arrancarlo | `docker compose up -d` |
| Ver si algo falla | `docker compose ps` y `docker compose logs api --tail 50` |
| Regenerar la misión simulada | `docker compose run --rm seed` |
| Actualizar el código | `git pull` y después `docker compose up -d --build` |

**Al cambiar de día:** la misión se genera relativa a la fecha de hoy. Al día siguiente ya no habrá check-in ni planes «de hoy». Vuelve a ejecutar `docker compose run --rm seed`, o fija `ORBIVIA_TODAY` en `.env` y reinicia con `docker compose up -d`.

**Cada siembra cambia las contraseñas**, salvo que hayas definido `DEMO_PASSWORD`.

---

## 8. Solución de problemas

**La página sale en blanco.** Recarga forzando (Cmd+Shift+R en Mac, Ctrl+Shift+R en Windows o Linux) o abre una ventana de incógnito. Comprueba que estás en `http://127.0.0.1:8080` y que `frontend` está `healthy`.

**«Usuario o contraseña incorrectos».** Las contraseñas cambian en cada siembra. Mira `volumenes/demo/credenciales.txt`.

**`Define … en .env`.** Falta esa variable en tu `.env`. Cópiala de `.env.example`.

**`port is already allocated`.** Otro programa usa ese puerto, a menudo un PostgreSQL local en el 5432. Cambia el puerto en `.env` (`POSTGRES_PORT=5433`, `FRONTEND_PORT=8081`…) y vuelve a ejecutar `docker compose up -d`.

**`docker: command not found` o `Cannot connect to the Docker daemon`.** Docker Desktop no está abierto. Ábrelo y espera a que diga *Running*.

**La siembra falla con `relation … does not exist` o `password authentication failed`.** La carpeta de datos de PostgreSQL ya existía de antes, sin estos esquemas o con otras claves. Los scripts de inicialización solo corren sobre una carpeta vacía. Pon en `.env` una carpeta nueva, por ejemplo `POSTGRES_DATA_DIR=./volumenes/postgre-orbivia`, y repite `docker compose up -d` y `docker compose run --rm seed`.

**`worker-ml` aparece `unhealthy` o se reinicia.** Docker no tiene memoria suficiente: sube la memoria en *Settings → Resources* a 6 GB o más. Mira el motivo con `docker compose logs worker-ml --tail 30`.

**Empezar de cero.** Primero para todo:

```bash
docker compose down
```

Después apunta `POSTGRES_DATA_DIR` a una carpeta nueva en `.env`, o borra a mano la carpeta de datos actual si estás seguro de que no la necesitas (se pierde la misión simulada y las cuentas de demo). Luego vuelve al §4.

---

## 9. Comprobar que todo funciona (opcional)

Con Orbivia arrancado y la misión sembrada, los tests de integración comprueban permisos por rol, privacidad multimedia, planes y sincronización con Tierra. Necesitan Python 3.12 o superior en tu equipo:

```bash
python3 -m pip install pytest httpx "psycopg[binary]"
```

```bash
python3 -m pytest tests/integration
```

Después vuelve a sembrar (`docker compose run --rm seed`), porque los tests dejan datos de prueba (un check-in, un audio sintético y decisiones de plan).

---

Más información: [README.md](README.md) (qué hace Orbivia, arquitectura y limitaciones), [docs/privacidad_y_alcance.md](docs/privacidad_y_alcance.md) y [docs/vector_estado_colapsado.md](docs/vector_estado_colapsado.md).
