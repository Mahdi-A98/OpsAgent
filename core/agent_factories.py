from devops_agents.docker.agents import DockerAgentFactory
# from db_agent.agent import DBAgentFactory
from core.schemas import TaskInput

# Example: select which agent to use dynamically
factories = {
    "docker": DockerAgentFactory(),
    # "db": DBAgentFactory(),
}

agent_type = "docker"
factory = factories[agent_type]
agent = factory.create_agent()

task = TaskInput(action="run_container")
result = agent.execute(task)

print(result)
# ✅ Always TaskOutput, no matter which agent
