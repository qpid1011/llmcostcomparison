# 🧮 LLMCostComparison.com — Live LLM API Token Price Index & Savings Calculator

Real-time, normalized per-million token rates (`$/1M input`, `$/1M output`, and `3:1 blended $/1M`), context window specs, and interactive monthly inference cost calculator across 25 Frontier Proprietary Labs and Open-Weight Inference Clouds.

- **Live Web App**: [https://llmcostcomparison.com](https://llmcostcomparison.com)
- **Live JSON Feed**: [`/llm_costs.json`](https://llmcostcomparison.com/llm_costs.json) (updated every 6 hours via GitHub Actions)
- **Daily Historical Snapshots**: `/history/YYYY-MM-DD.json`

## Methodology
1. **Live Upstream Sources**: Automated Python 3.11 sync (`scripts/sync_llm_costs.py`) queries unauthenticated public catalogs from OpenRouter (`openrouter.ai/api/v1/models`) and LiteLLM (`BerriAI/litellm`) every 6 hours (`25 */6 * * *`), enforcing an 80-model minimum circuit breaker before updating live feeds.
2. **3:1 Blended Token Rate**: Production RAG, coding agents, and multi-turn chat workloads typically consume ~3 input tokens per generated output token. Blended rates follow the industry standard formula: `(3 × Input $/1M + 1 × Output $/1M) / 4`.
3. **Tracked Providers & Clouds**: OpenAI, Anthropic, Google, DeepSeek, Meta Llama, Qwen, Mistral AI, xAI, Cohere, Moonshot (Kimi), Z.ai (GLM), NVIDIA Nemotron, MiniMax, Groq, Cerebras, SambaNova, Together AI, Fireworks AI, DeepInfra, Baseten, Novita AI, Nebius AI, Hyperbolic, and Anyscale.
