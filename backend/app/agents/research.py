from app.agents.base import AgentContext, AgentInput, AgentOutput, BaseAgent


class ResearchAgent(BaseAgent):
    agent_type = "research"

    async def run(self, context: AgentContext, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent_type=self.agent_type,
            status="completed",
            summary="Returned deterministic research notes.",
            data={
                "mission_id": str(context.mission_id),
                "findings": [],
                "sources": [],
            },
        )
