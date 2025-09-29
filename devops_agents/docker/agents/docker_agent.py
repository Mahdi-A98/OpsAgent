import os
import uuid
import sqlite3
from dotenv import load_dotenv
from IPython.display import Image, display

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import MessagesState, StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from typing import Literal, Optional
from typing_extensions import TypedDict

from core.base import OpsAgent, OpsAgentFactory
from core.schemas import TaskInput, TaskOutput
from core.utils import printers
from core.utils.search_tools import search_web, tavily_search, url_extractor
from devops_agents.docker.tools import all_container_tools
from devops_agents.docker.prompts import docker_agent_main_prompt



class State(TypedDict):
    input: str


class DockerAgent(OpsAgent):
    def __init__(self,
                api_key,
                connection=None,
                model="gpt-4.1-mini",
                client=ChatOpenAI,
                client_config: Optional[dict] = None,
                memory_saver=SqliteSaver,
                output_color="warm_blue"):
        
        self.model = model
        self.api_key = api_key
        self.client = client(api_key=api_key, **(client_config or {}))
        self.memory = memory_saver(connection) if connection else None
        self._graph = None
        self.output_color = output_color
        
    @property
    def graph(self):
        if not self._graph:
            self._graph = self.create_graph()
        return self._graph
    
    def execute(self, task: TaskInput) -> TaskOutput:
        return super().execute(task)
    
    def get_status(self) -> dict:
        return super().get_status()

    def run(self, question: str, config=None) -> str:
        result = self.graph.invoke(
            MessagesState({"messages": [{"role": "user", "content": question}]}),
            config
        )
        final_message = result["messages"][-1].content
        return final_message
    
    def run_loop(self, thread_id=None):
        thread_id = thread_id or uuid.uuid4()
        config = {"configurable": {"thread_id":thread_id }}
        user_input = input("Hello I'm docker agent. how can i help you?\n>>  ")
        while True:
            if user_input in ["quit", "exit", "end"]:
                break
            response = self.run(user_input, config)
            printers[self.output_color](response)
            user_input = input(">>  ")
    
    def create_graph(self):
        model = self.client
        tools =  all_container_tools
        tools.extend(
            [
                # search_web,
                # url_extractor,
                tavily_search
            ]
        )
        agent = create_react_agent(model, tools, prompt=docker_agent_main_prompt)
        workflow = StateGraph(MessagesState)
        workflow.add_node("agent", agent)
        workflow.set_entry_point("agent")
        workflow.add_edge("agent", END)
        graph = workflow.compile(checkpointer=self.memory)
        return graph
    
    def display_agent(self, display_type:Literal["stdout", "ipython"]="ipython"):
        if display_type == "ipython":
            try:
                return display(Image(self.graph.get_graph().draw_mermaid_png()))
            except Exception:
                print(self.graph.get_graph().draw_mermaid())
        elif display_type == "stdout":
            print(self.graph.get_graph().draw_mermaid())


class DockerAgentFactory(OpsAgentFactory):
    
    def create_agent(self, *args, **kwargs) -> DockerAgent:
        return DockerAgent(*args, **kwargs)
    
        
        
def run_docker_agent():
    load_dotenv()
    db_name = os.environ.get("DOCKER_AGENT_CHAT_DB", ":memory:")
    conn = sqlite3.connect(db_name, check_same_thread = False)
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set in .env file")
    docker_agent_factory = DockerAgentFactory()
    docker_agent = docker_agent_factory.create_agent(api_key=openai_api_key, connection=conn)
    docker_agent.display_agent(display_type="stdout")
    docker_agent.run_loop()
    
if __name__ == "__main__":
    run_docker_agent()