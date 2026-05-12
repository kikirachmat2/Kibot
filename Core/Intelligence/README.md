# 🧠 KiBot Intelligence

AI Orchestration, Learning, and Market Intelligence models.

## Ringkas
- `aggregator.py` menggabungkan konteks portfolio, market, dan historis council.
- `kibot_ai_coordinator.py` mengatur alur AI dan provider fallback.
- `kibot_learning_engine.py` menyimpan state belajar dan validasi integritas.

## Responsibility
- **AI Veto**: Validating signals using local LLMs (Ollama/Dify).
- **What-If Analysis**: Simulating market conditions before execution.
- **Learning Cycle**: Continuous improvement of trading parameters.
- **RAG Context**: Providing local system knowledge to AI agents.

## Key Files
- `kibot_ai_coordinator.py`: Main AI signal processor.
- `kibot_whatif_engine.py`: Mathematical risk simulator.
- `kibot_rag.py`: Local knowledge retrieval.
- `kibot_learning_engine.py`: Performance optimization.
