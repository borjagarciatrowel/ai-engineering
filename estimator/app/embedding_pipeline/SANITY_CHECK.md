# SANITY_CHECK — embeddings discrimination (Session 7)

This is **not** a formal retrieval evaluation. It is a minimum acceptable check
that the pipeline runs end-to-end and that the embeddings discriminate
reasonably between semantically close and far texts.

Model: `text-embedding-3-small` (1536 dims). Similarity: cosine, computed by
hand in [`scripts/compare.py`](../../scripts/compare.py).

## Results

| Pair | Expectation | Cosine similarity |
|------|-------------|-------------------|
| A — semantically close | high (≳ 0.6) | _pending funded key_ |
| B — unrelated          | low (≲ 0.4)  | _pending funded key_ |
| C — generic / ambiguous | no fixed expectation | _pending funded key_ |

> ⚠️ **Status of the numeric run.** The three numbers above were not captured
> yet: the OpenAI key currently in `estimator/.env` returns
> `429 insufficient_quota` (the embeddings API rejects the request before
> producing a vector). The pipeline itself is verified — chunking, schema
> validation and the FastAPI route all work, and the rate-limit retry path was
> exercised by this very error. To fill the table, point `.env` at a funded
> `OPENAI_API_KEY` and re-run the three commands below; the values drop straight
> in.

## Commands (run exactly these three pairs)

```bash
# Pair A — semantically close (expect high)
uv run python scripts/compare.py \
  --text-a "OAuth 2.0 authentication backend with JWT tokens for fintech mobile app" \
  --text-b "Authorization service using JSON Web Tokens for a banking application"

# Pair B — unrelated (expect low)
uv run python scripts/compare.py \
  --text-a "OAuth 2.0 authentication backend with JWT tokens for fintech mobile app" \
  --text-b "Database migration from MySQL to PostgreSQL with zero downtime"

# Pair C — generic / ambiguous (no fixed expectation)
uv run python scripts/compare.py \
  --text-a "Backend services" \
  --text-b "API development"
```

(Equivalently inside Docker: `docker compose exec estimator python scripts/compare.py --text-a "..." --text-b "..."`.)

## Comentario (sobre la expectativa)

- **Pareja A** describe el mismo concepto con vocabulario distinto (OAuth/JWT
  ↔ "JSON Web Tokens", fintech ↔ banking). Esperamos similitud alta: si saliera
  baja, el modelo no estaría capturando sinónimos de dominio.
- **Pareja B** enfrenta autenticación contra una migración de base de datos: dos
  dominios sin solape. Esperamos similitud claramente menor que A; es el control
  negativo que demuestra que el embedding sí discrimina.
- **Pareja C** son dos etiquetas genéricas y cortas ("Backend services" vs
  "API development"). Sin contexto, los textos muy cortos tienden a dar
  similitudes medias-altas y poco informativas; es justo el caso interesante
  para comentar en directo (qué pasa cuando el chunk no lleva contexto del
  padre — exactamente lo que el *contextual chunk header* del chunker evita en
  la pipeline real).

Cuando se rellenen los números, lo esperable es **A > C > B** o, como mínimo,
**A > B** con un margen cómodo. Cualquier resultado que rompa eso (p. ej. B ≈ A)
sería material de discusión para la sesión en vivo.
