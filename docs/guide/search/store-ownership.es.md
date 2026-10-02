# Propiedad de los almacenes

Tres hechos hacen que importe quién cierra un almacén:

- `aclose()` en un almacén SQLite no es definitivo: una llamada posterior
  vuelve a abrir la conexión.
- `async with pipeline` cierra cada elemento de `closeables` cada vez que se
  sale del bloque.
- El cerrojo de un almacén pertenece al primer bucle de eventos que compite por
  él. Usar la misma instancia desde un segundo bucle falla, pero solo cuando
  ambos la usan a la vez, así que una prueba tranquila pasa y una interfaz
  ocupada se rompe.

Por eso, da a cada instancia de almacén exactamente **un propietario**, el
ámbito que sobrevive a todos sus usuarios, y deja que solo el propietario llame
a `aclose()`. Usa cada instancia desde **un solo bucle de eventos**. Todo lo
demás la toma prestada: `AsyncHybridSearcher`, las fuentes de aristas y
`AsyncCompositeIngestor` nunca cierran un almacén.

| Despliegue | Propietario de los almacenes SQLite | `closeables` del pipeline |
|------------|-------------------------------------|---------------------------|
| Pipeline e interfaz en procesos separados | cada proceso, para las instancias que abrió sobre los archivos compartidos | enumera las instancias propias del pipeline |
| Script de un solo uso que ingiere y consulta dentro de `async with pipeline` | el pipeline | enumera los almacenes; las consultas se ejecutan dentro del bloque |
| Aplicación de larga duración en un bucle de eventos que inicia ejecuciones de ingesta | la aplicación, que los cierra al apagarse | **no** debe enumerarlos, o el final de cada ejecución los cierra y la siguiente consulta reabre una conexión sin propietario |
| `ETLPipeline` bloqueante más una aplicación en su propio bucle | dos conjuntos de instancias sobre los mismos archivos: uno lo usa el bucle en segundo plano del pipeline y otro el bucle de la aplicación | enumera el conjunto del pipeline |

El modo WAL de SQLite permite que un proceso lea mientras otro escribe.
