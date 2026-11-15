# Privacidad, alcance del modelo de texto y afirmaciones por verificar

## Garantías implementadas

| Requisito | Dónde se cumple |
|---|---|
| Audio y vídeo solo en RAM | `media-broker`: Redis sin AOF ni RDB, en tmpfs, stream con MAXLEN 10. `workers/media_worker.py` decodifica con ffmpeg por tuberías, hace XACK + XDEL tras guardar los números y vacía los búferes. Test: `test_media_is_processed_in_memory_and_purged` (ningún fichero nuevo en el contenedor). |
| Sin transcripciones | No existe ninguna columna para guardarlas. Con `ENABLE_NLP=true`, el texto solo vive mientras se clasifica. El router HTTP de `procesamiento/texto`, que devolvía la transcripción, no se monta. |
| Error de procesamiento sin rastro | El mensaje se borra igualmente y se registra solo el código de error. Test: `test_invalid_media_leaves_nothing_behind`. |
| Trabajos no perdidos | Hasta guardar el resultado, el mensaje sigue pendiente en el grupo de consumo. Al reiniciar se recupera con XAUTOCLAIM. |
| Roles de BD de privilegio mínimo | `base-de-datos/init/03_roles.sh`. El motor y sync-tierra no tienen USAGE sobre `private_cycle`. La API solo ve el seudónimo en `vault_identity.astronauts`. Test: `test_engine_and_sync_roles_cannot_read_private_cycle`. |
| Ciclo cifrado y desacoplado | `pgp_sym_encrypt` con `CYCLE_ENCRYPTION_KEY`, rol `orbivia_cycle` propio. Compartición temporal (máx. 72 h) y borrado total. |
| Grafo social fuera del reparto | `crew_planner` rechaza la entrada `social`. La imagen de la API solo contiene `social_graph/intervals.py`. Test: `test_social_graph_is_rejected_as_input`. |
| RBAC en el backend | `api/auth.py` (`require`) y filtrado por rol en `api/views.py`. Tests en `tests/integration`. |
| Envío a Tierra | Lista blanca en `sync-tierra/sync_tierra/whitelist.py`, huella SHA-256 y receptor que descarta duplicados. |

## Tensión del modelo de texto (README §2.C y §1)

El README define cuatro puntuaciones de texto, entre ellas "ánimo bajo" y "ansiedad". La prohibición del art. 5.1.f del Reglamento de IA afecta a la inferencia de emociones en el trabajo, salvo por motivos médicos o de seguridad. El README apoya el uso en esa excepción y limita la visibilidad al médico de a bordo y al equipo médico en Tierra.

No se puede garantizar desde el software que el uso se mantenga dentro de esa excepción. Por eso:

- **`ENABLE_NLP=false` por defecto.** El modelo no se carga y los cuatro campos del vector quedan ausentes. La acústica (openSMILE) sí se calcula.
- Las puntuaciones solo se exponen a `flight_surgeon` y `earth_medical`. La nota de disponibilidad que ve el comandante solo muestra un motivo general.
- El modelo (`Hrishikesh4/mental-health-classifier-longformer`, multietiqueta) da la confianza del clasificador, no una escala clínica. No se ha validado en español ni con respuestas a estas ocho preguntas. Activarlo requiere esa validación y la decisión del responsable de protección de datos.

## Afirmaciones jurídicas del README pendientes de verificación

Se conservan tal como están, pero **no se han verificado** en esta integración:

- "Reglamento (UE) 2026/1744 (Digital Omnibus)" y la fecha del 2 de diciembre de 2027 para las obligaciones de alto riesgo del anexo III.
- "Sentencia del TJUE de 2 de julio de 2026 (C-427/24, Diagramm Halbach)" sobre software como producto sanitario.
- La aplicación concreta del art. 9.2.h del RGPD a la tripulación y del 9.2.j con art. 89 al uso en investigación.

## Datos simulados

Todo lo que genera `simulador/seed_mission.py` es ficticio. La tabla `operations.mission` lleva `simulated = true`, las filas llevan `source = 'simulated'` y el vector, su `simulated_mask`. La interfaz muestra "Datos simulados" en todo momento. Las variables pendientes de validación instrumental (peso, glóbulos rojos, EEG) se marcan `validated = false`.
