# Session 10 — hybrid search + reranking, measured

Golden set: [`evals/golden_retrieval.json`](golden_retrieval.json), 5 queries, relevance
annotated by hand against `data/budgets_sample.json` (17 historical budgets). Precision@5 is
computed per chunk: a returned chunk counts as a hit if its `metadata.budget_id` is in the
query's annotated relevant set. Run with:

```bash
docker compose up -d estimator-postgres
uv run alembic upgrade head
uv run python scripts/eval_retrieval_s10.py
```

## Results

| Config | Search    | Reranking | Precision@5 | Latency (ms) |
|--------|-----------|-----------|-------------:|--------------:|
| A      | Vectorial | No        | 0.80         | 955\*         |
| B      | Híbrida   | No        | 0.80         | 249           |
| C      | Vectorial | Sí        | 0.84         | 8882          |
| D      | Híbrida   | Sí        | 0.84         | 7392          |

\* Config A corrió primero en el script y absorbió el coste de conexión en frío a la API de
OpenAI (2 de las 5 consultas salieron a 1.1-2.9s; el resto ronda los 240ms, igual que B). No es
una diferencia real vectorial-vs-híbrida — es orden de ejecución. La comparación honesta de
latencia sin reranking es A ≈ B ≈ 240-250ms por consulta.

Por consulta (precision@5), en orden A/B/C/D:

| Query | A | B | C | D |
|---|---|---|---|---|
| q1_mobile_banking | 0.80 | 0.80 | 0.80 | 0.80 |
| q2_marketplace | 0.80 | 0.80 | 0.80 | 0.80 |
| q3_telemedicine | 0.80 | 0.80 | 1.00 | 1.00 |
| q4_factory_iot | 0.60 | 0.60 | 0.60 | 0.60 |
| q5_mvp_store | 1.00 | 1.00 | 1.00 | 1.00 |

## Conclusiones

Para este caso de uso usaría la **configuración B (híbrida, sin reranking)**. La búsqueda
híbrida no cambió la precisión frente a la vectorial pura en este golden set (0.80 en ambas:
las cinco consultas están redactadas con vocabulario técnico en inglés muy parecido al de los
chunks, así que el ranking léxico y el vectorial coinciden en top-5), pero tampoco cuesta nada
— sigue una única llamada de embedding más una consulta SQL de texto completo, unos pocos ms de
más. Es una mejora "gratis" que dejaría activada aunque hoy no se note en las métricas, porque en
consultas con nombres propios o jerga exacta (nombres de tecnologías, siglas) el matching léxico
sí puede rescatar un chunk que la búsqueda vectorial pura deja fuera del top-k, y este golden set
de 5 consultas es demasiado pequeño para descartarlo. El reranking, en cambio, **no lo justifico
para este flujo**: pasar de 0.80 a 0.84 de precisión (una consulta, q3, gana un chunk relevante
más) cuesta multiplicar la latencia por ~30 (de ~250ms a ~7.4-8.9s), y esa espera ocurre en el
camino síncrono de una petición HTTP que el usuario está esperando. Si el reranking se ejecutara
en un flujo asíncrono/offline (por ejemplo, re-rankeando resultados ya mostrados, o en un batch
nocturno para presupuestos que se van a reutilizar), la cuenta cambiaría — pero tal como está
integrado hoy, el coste no compensa la ganancia.
