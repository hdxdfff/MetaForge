from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

try:
    from crewai import Agent, Crew, Process, Task
except ImportError as exc:
    raise SystemExit(
        "CrewAI is not installed. Run .\\run.ps1 -Install first."
    ) from exc


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def configure_openai_compatible_env() -> None:
    dashscope_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if dashscope_key:
        os.environ["OPENAI_API_KEY"] = dashscope_key
        os.environ["OPENAI_BASE_URL"] = os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        if not os.getenv("OPENAI_MODEL_NAME"):
            os.environ["OPENAI_MODEL_NAME"] = os.getenv("DASHSCOPE_TEXT_MODEL", "qwen-plus")


def main() -> None:
    configure_openai_compatible_env()
    require_env("OPENAI_API_KEY")
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

    researcher = Agent(
        role="Research Analyst",
        goal="Extract the most important facts from a user request.",
        backstory="A concise analyst who identifies useful facts quickly.",
        llm=model_name,
        verbose=True,
    )

    writer = Agent(
        role="Brief Writer",
        goal="Turn research notes into a short, usable answer.",
        backstory="A pragmatic writer focused on clarity and actionability.",
        llm=model_name,
        verbose=True,
    )

    user_request = "Explain what CrewAI is useful for in 5 bullet points."

    research_task = Task(
        description=f"Analyze this request and extract the key points: {user_request}",
        expected_output="A short set of research notes.",
        agent=researcher,
    )

    writing_task = Task(
        description="Write a concise final answer based on the research notes.",
        expected_output="Exactly 5 bullet points.",
        agent=writer,
    )

    crew = Crew(
        agents=[researcher, writer],
        tasks=[research_task, writing_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    print("\n=== CrewAI Result ===\n")
    print(result)


if __name__ == "__main__":
    main()
