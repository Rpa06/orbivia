# orbivia

## Despliegue local con Docker

Requisitos: Docker Desktop (o Docker Engine) con Docker Compose v2.

1. Copia `.env.example` a `.env` y cambia `POSTGRES_PASSWORD`.
2. Desde la raíz del repositorio, construye y levanta los servicios:

   ```powershell
   Copy-Item .env.example .env
   docker compose up --build -d
   ```

3. Abre <http://localhost:8080>. La API está disponible en
   <http://localhost:8000/health/live> y su comprobación de dependencias en
   <http://localhost:8000/health/ready>.
4. Consulta el estado y los registros con `docker compose ps` y
   `docker compose logs -f`.
5. Para detener los servicios sin borrar los datos persistidos, ejecuta
   `docker compose down`. Los datos quedan en `volumenes/postgre` y
   `volumenes/redis`.

PostgreSQL usa pgvector y ejecuta los scripts de `base-de-datos/init` únicamente
cuando inicializa un directorio de datos vacío. Redis persiste su AOF en
`volumenes/redis`. Los puertos de PostgreSQL y Redis solo se publican en la
interfaz local; el frontend y la API usan los puertos configurables en `.env`.

Este despliegue proporciona la infraestructura y endpoints de salud iniciales.
Los contenedores `worker-stream` y `worker-ml` son scaffolding: comprueban la
conexión con Redis, pero todavía no consumen señales ni ejecutan lógica ML.
La interfaz web también es una página inicial. Sustituye estos componentes
cuando se implementen los procesadores y la aplicación de producto.
