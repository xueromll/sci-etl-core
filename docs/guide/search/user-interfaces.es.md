# Crear una interfaz de usuario

`sci_etl_core.discovery` contiene el modelo de lectura que representa una capa
de presentación: `DiscoveryResult` (el texto de la consulta y sus chips, los
resultados fusionados, el grafo, las facetas, el número de coincidencias, el
tiempo transcurrido y las ramas degradadas u omitidas) y `Facet`. Ambas son
dataclasses inmutables, e importar el módulo no carga ningún almacén, ninguna
maquinaria del bucle de eventos ni ninguna dependencia opcional.

Representa `FusedHit.snippets` con tu propio marcado a partir de sus
`highlights`, una línea por campo, y etiqueta un resultado cuyo `lexical_rank`
sea `None` como coincidencia por significado. Construye histogramas de fechas o
años a partir de `range_counts`, que mantiene visibles todos los intervalos
mientras uno está seleccionado.

Mantén el análisis de la consulta en cada pulsación de tecla y haz asíncrona
solo la recuperación: aplica un retardo (debounce), cancela una búsqueda cuando
empiece otra más reciente y descarta cualquier resultado que llegue después de
que comenzara una búsqueda más reciente.

Antes de compartir almacenes entre una interfaz y las ejecuciones de ingesta,
lee [Propiedad de los almacenes](store-ownership.md).
