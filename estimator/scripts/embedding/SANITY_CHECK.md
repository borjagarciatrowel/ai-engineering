# SANITY_CHECK — embeddings discrimination (Session 7)

This is **not** a formal retrieval evaluation. It is a minimum acceptable check
that the pipeline runs end-to-end and that the embeddings discriminate
reasonably between semantically close and far texts.

Model: `text-embedding-3-small` (1536 dims). Similarity: cosine, computed by
hand in [`compare.py`](compare.py) (same folder).

## Results

| Pair | Expectation | Cosine similarity |
|------|-------------|-------------------|
| A — semantically close | high (≳ 0.6) | **0.5957** |
| B — unrelated          | low (≲ 0.4)  | **0.1920** |
| C — generic / ambiguous | no fixed expectation | **0.5407** |

Observed order: **A (0.60) > C (0.54) > B (0.19)**.

## Commands (run exactly these three pairs)

```bash
# Pair A — semantically close (expect high)
uv run python scripts/embedding/compare.py \
  --text-a "OAuth 2.0 authentication backend with JWT tokens for fintech mobile app" \
  --text-b "Authorization service using JSON Web Tokens for a banking application"

# Pair B — unrelated (expect low)
uv run python scripts/embedding/compare.py \
  --text-a "OAuth 2.0 authentication backend with JWT tokens for fintech mobile app" \
  --text-b "Database migration from MySQL to PostgreSQL with zero downtime"

# Pair C — generic / ambiguous (no fixed expectation)
uv run python scripts/embedding/compare.py \
  --text-a "Backend services" \
  --text-b "API development"
```

(Equivalently inside Docker: `docker compose exec estimator python scripts/embedding/compare.py --text-a "..." --text-b "..."`.)

## Comentario

- **Pareja A (0.5957)** — es, junto con C, la más alta, así que el modelo **sí**
  capta que es la pareja más relacionada: reconoce los sinónimos de dominio
  (OAuth/JWT ↔ "JSON Web Tokens", fintech ↔ banking). El detalle llamativo es
  que se queda **justo por debajo** del 0.6 orientativo: la reformulación
  completa con vocabulario distinto basta para no superar el umbral. Encaja con
  la intuición, pero recuerda que ese 0.6 es una guía, no una frontera dura.
- **Pareja B (0.1920)** — claramente baja, como se esperaba (≲ 0.4). Es el
  control negativo que funciona: autenticación vs migración de base de datos no
  comparten dominio y el embedding lo refleja. Aquí el pipeline discrimina bien.
- **Pareja C (0.5407)** — **el resultado sorprendente**: dos etiquetas genéricas
  y cortas ("Backend services" vs "API development"), que no son sinónimas, dan
  una similitud casi tan alta como la pareja A. Es el efecto típico de los textos
  muy cortos y vagos: sin contexto colapsan hacia el mismo macro-dominio
  (desarrollo backend) y resultan poco discriminables. Es justo el argumento a
  favor del *contextual chunk header* del chunker: sin el contexto del
  presupuesto padre, los chunks genéricos se volverían indistinguibles entre sí.

**Conclusión:** se cumple **A ≫ B** con margen cómodo (0.60 vs 0.19), que es el
mínimo que pide el sanity check. Los dos puntos de discusión para el directo:
(1) A se queda rozando por debajo de 0.6, y (2) C ≈ A — una pareja genérica casi
tan "parecida" como una realmente sinónima. Ambos refuerzan que la calidad del
texto que se embebe (contexto, longitud, especificidad) importa tanto como el
modelo.
