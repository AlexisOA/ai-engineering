# Sanity check — text-embedding-3-small

Generated with `scripts/compare.py`, real calls against `text-embedding-3-small`.

| Pair | Text A | Text B | Cosine similarity |
|------|--------|--------|-------------------:|
| A (close) | "OAuth 2.0 authentication backend with JWT tokens for fintech mobile app" | "Authorization service using JSON Web Tokens for a banking application" | 0.5957 |
| B (unrelated) | "OAuth 2.0 authentication backend with JWT tokens for fintech mobile app" | "Database migration from MySQL to PostgreSQL with zero downtime" | 0.1920 |
| C (generic) | "Backend services" | "API development" | 0.5408 |

## Comentario

El pipeline discrimina razonablemente: la pareja B (temas no relacionados) cae
muy por debajo de la pareja A (mismo dominio, distinta redacción), una
diferencia de 0.40 puntos que es justo lo que se espera de un embedding útil.
Lo que sí llama la atención es que A (0.5957) queda ligeramente por debajo del
umbral orientativo de 0.6 pese a describir el mismo concepto (auth OAuth/JWT
para fintech/banca) con vocabulario distinto — el modelo parece premiar más la
superposición léxica exacta ("JWT"/"JSON Web Tokens" sí coinciden, pero
"fintech mobile app" vs "banking application" introduce más distancia de la
esperada). Lo más sorprendente es la pareja C: dos frases de dos palabras,
genéricas y sin relación temática explícita ("Backend services" / "API
development"), obtienen 0.5408 — casi tan alto como la pareja A que sí
comparte dominio semántico real. Mi lectura es que con textos tan cortos el
embedding captura sobre todo "esto es jerga de desarrollo de software backend"
como señal dominante, sin mucha superficie textual para diferenciar más allá
de eso — un caso concreto para discutir en directo sobre los límites de
comparar frases muy cortas y genéricas.
