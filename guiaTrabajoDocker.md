> **Nota (rama de integración):** el `.env` de esta guía está desactualizado y con él el proyecto ya no arranca, porque faltan claves obligatorias. Para instalar y arrancar Orbivia usa [GUIA_ACTIVACION.md](GUIA_ACTIVACION.md). Las explicaciones sobre cómo se comunican los contenedores siguen siendo válidas.

Aquí tienes la guía adaptada exactamente a la arquitectura de **Orbivia**, pensada para alguien que nunca ha tocado Docker o lo usa lo mínimo posible.

---

## Guía de conexión y uso de Docker para Orbivia

### 0. Antes de empezar: prepara tu archivo `.env`

Tu `docker-compose.yml` exige que exista una contraseña definida (`POSTGRES_PASSWORD`). Si no la creas, Docker te dará un error y no arrancará.

1. En la carpeta raíz del proyecto, crea un archivo llamado exactamente `.env` (o copia el `.env.example` si existe).
2. Pega dentro las variables del final:
```env
POSTGRES_DB=orbivia
POSTGRES_USER=orbivia
POSTGRES_PASSWORD=cambia-esta-clave-local
POSTGRES_PORT=5432
REDIS_PORT=6379
API_PORT=8000
FRONTEND_PORT=8080

```


3. Abre una terminal en esa carpeta y arranca todo con:
```bash
docker compose up -d --build

```


*(La primera vez tardará unos minutos mientras descarga PostgreSQL, Redis y compila Python/Frontend).*

---

### 1. Cómo se conectan los contenedores entre sí (Desde el código)

Cuando ejecutas Docker Compose, se crea una red interna privada donde **no existe `localhost**` para comunicarse entre servicios. Si el código de `api` o de un `worker` intenta conectarse a `localhost:5432`, fallará porque buscará PostgreSQL dentro de su propio contenedor.

En su lugar, **el nombre del servicio en el `docker-compose.yml` actúa como su dirección IP o dominio**:

| Servicio origen | Servicio destino | Host (Dirección) | Puerto interno | Uso en el código / Variables |
| --- | --- | --- | --- | --- |
| `api` | **Base de datos (`db`)** | `db` | `5432` | `POSTGRES_HOST=db` |
| `api` / `workers` | **Redis (`broker`)** | `broker` | `6379` | `REDIS_HOST=broker` |
| `frontend` (si usa proxy Nginx) | **Backend (`api`)** | `api` | `8000` | `http://api:8000` |

> **Nota para los Workers (`worker-stream` y `worker-ml`):** Fíjate en que en tu `docker-compose.yml` actual, los workers tienen configurado `REDIS_HOST: broker`, pero **no** tienen las variables de `POSTGRES_*`. Si en algún momento esos workers necesitan leer o escribir directamente en PostgreSQL (sin pasar por la API), tendrás que añadirles las mismas variables `POSTGRES_HOST: db`, `POSTGRES_DB`, `POSTGRES_USER` y `POSTGRES_PASSWORD` que tiene `api`.

---

### 2. Cómo conectarte tú desde tu ordenador (Navegador, DBeaver, Postman)

Cuando usas un programa instalado en tu ordenador (fuera de Docker), sí debes usar **`localhost`** o **`127.0.0.1`**. Tu `docker-compose.yml` tiene una configuración muy buena por seguridad: `db` y `broker` solo aceptan conexiones desde tu propia máquina (`127.0.0.1`).

#### A) Ver la web y probar la API

* **Frontend (Web):** Abre tu navegador en `http://localhost:8080`
* **API (Swagger / Docs de FastAPI):** Abre `http://localhost:8000/docs`

#### B) Conectarte a PostgreSQL con un programa visual (DBeaver, pgAdmin, TablePlus, DataGrip)

Abre tu gestor de bases de datos, crea una nueva conexión de tipo **PostgreSQL** e introduce estos datos:

* **Host / Servidor:** `127.0.0.1` (o `localhost`)
* **Puerto:** `5432` *(si cambiaste `POSTGRES_PORT` en tu `.env`, pon ese número)*
* **Base de datos:** `orbivia`
* **Usuario:** `orbivia`
* **Contraseña:** `cambia-esta-clave-local` *(o la que pusieras en `POSTGRES_PASSWORD` en `.env`)*

#### C) Conectarte a PostgreSQL por terminal (sin instalar ningún programa)

Si solo quieres lanzar una consulta SQL rápida o comprobar si se han creado las tablas, ejecuta esto en tu terminal:

```bash
docker compose exec db psql -U orbivia -d orbivia

```

* **Para ver las tablas creadas:** escribe `\dt` y pulsa Enter.
* **Para salir:** escribe `\q` y pulsa Enter.

#### D) Conectarte a Redis por terminal (para ver las colas de los workers)

```bash
docker compose exec broker redis-cli

```

* **Para ver todas las claves guardadas:** escribe `KEYS *`
* **Para salir:** escribe `exit`

---

### 3. Chuleta de comandos diarios de Docker

No necesitas memorizar Docker; con estos 5 comandos cubres el 95% de tu día a día:

1. **Ver si todo está funcionando bien (y si los *healthchecks* están en verde):**
```bash
docker compose ps

```


*(Debes ver `healthy` o `running` en todos los servicios).*
2. **Ver qué está pasando o por qué falla algo (Logs en tiempo real):**
```bash
docker compose logs -f api

```


*(Cambia `api` por `worker-ml`, `worker-stream`, `db` o `frontend` según lo que quieras vigilar. Pulsa `Ctrl + C` para dejar de mirar sin apagar nada).*
3. **He cambiado código en Python o en el Frontend, ¿cómo lo actualizo?**
```bash
docker compose up -d --build

```


*(Solo reconstruirá los contenedores cuyo código haya cambiado y reiniciará lo necesario).*
4. **Apagar todo al terminar el día (sin perder los datos):**
```bash
docker compose down

```


*(Tus datos de PostgreSQL y Redis están a salvo porque se guardan en las carpetas `./volumenes/postgre` y `./volumenes/redis` de tu ordenador).*
5. **Empezar de cero absoluto (Borrar base de datos y reiniciar):**
```bash
docker compose down

```


Luego borra la carpeta `./volumenes/postgre` de tu proyecto y vuelve a ejecutar `docker compose up -d`. Al arrancar vacío, PostgreSQL volverá a ejecutar automáticamente los scripts que tengas en `./base-de-datos/init`.