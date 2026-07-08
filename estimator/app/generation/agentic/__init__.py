"""Agentic generation.

Two independent things live here:

* **The Actor-Critic-Boss loop** (Session 4/5): ``boss.py`` orchestrates iterative
  refinement; ``critic.py`` is the read-only auditor. Control flow is authored by
  us — the model fills gaps, it does not choose the next step.
* **The hand-written function-calling agent** (Session 12): ``agent_loop.py`` +
  ``agent_tools.py`` + ``agent_schemas.py``. Here the *model* decides the next
  action — a manual reason→act→observe loop over the raw OpenAI Responses API,
  the one deliberate exception to the "everything goes through ``LLMWrapper``"
  rule (seeing the loop by hand is the whole point of the exercise). Its tools
  wrap the S9–S10 ``retrieve()`` pipeline + deterministic cost/validation.

This layer MAY import ``app.generation.conversation`` (the multi-turn substrate
the ACB loop runs on); the reverse is forbidden.
"""
