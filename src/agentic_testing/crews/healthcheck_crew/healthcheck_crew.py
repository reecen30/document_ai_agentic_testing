"""
Minimal embedded crew for AMP project-structure compatibility checks.

This crew is not used by the main flow runtime.
"""
from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from agentic_testing.llm_factory import get_agent_llm


@CrewBase
class HealthcheckCrew:
    @agent
    def health_agent(self) -> Agent:
        return Agent(
            role="Healthcheck Agent",
            goal="Return a short deployment readiness confirmation.",
            backstory="A lightweight utility agent used for deployment structure checks.",
            llm=get_agent_llm("structured"),
            verbose=False,
        )

    @task
    def health_task(self) -> Task:
        return Task(
            description="Return JSON: {\"status\":\"ok\",\"component\":\"healthcheck_crew\"}",
            expected_output="A compact JSON object with status and component fields.",
            agent=self.health_agent(),
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )

