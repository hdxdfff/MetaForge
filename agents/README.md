# AI Agents Setup

This workspace contains two local setups:

- `crewai-starter`: a minimal CrewAI project that runs with the embedded Python in `D:\codex\tools\python311-embed`
- `autogpt-classic`: a bootstrap wrapper for the official AutoGPT classic repository

Both setups use environment variables from `.env` files. Copy the provided `.env.example` file to `.env` and fill in your API keys before running.

Recommended model provider:

- OpenAI-compatible endpoint with `OPENAI_API_KEY`

Important limitation:

- AutoGPT's current official self-hosted platform expects Docker. Docker is not installed on this machine, so the included AutoGPT setup targets the classic repository bootstrap path instead.
