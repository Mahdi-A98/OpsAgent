import sqlite3
import aiosqlite
from core import settings
from devops_agents.docker.agents.docker_agent import DockerAgentFactory

from langchain_core.messages import HumanMessage
from langchain.memory import ConversationBufferMemory
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain.schema.runnable.config import RunnableConfig
from langchain.schema.runnable import Runnable, RunnableLambda

from chainlit.types import ThreadDict
import chainlit as cl

from operator import itemgetter


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    if (username, password) == ("admin", "admin"):
        return cl.User(
            identifier="admin",
            metadata={
                "role": "admin",
                "provider": "credentials"
            }
        )
    else:
        return None


@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set(
        "memory",
        ConversationBufferMemory(return_messages=True)
    )
    setup_runnable()


def setup_runnable():
    memory = cl.user_session.get("memory")  # type: ConversationBufferMemory
    conn = aiosqlite.connect(settings.DOCKER_AGENT_CHAT_DB, check_same_thread=False)
    docker_agent_factory = DockerAgentFactory()
    docker_agent = docker_agent_factory.create_agent(
        api_key=settings.OPENAI_API_KEY,
        connection=conn,
        memory_saver=AsyncSqliteSaver,
    )
    docker_agent.graph.assign(
        history=RunnableLambda(memory.load_memory_variables) | itemgetter("history")
    )
    cl.user_session.set("runnable", docker_agent.graph)


    
@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict):
    memory = ConversationBufferMemory(return_messages=True)
    root_messages = [m for m in thread["steps"] if m["parentId"] == None]
    for message in root_messages:
        if message["type"] == "user_message":
            memory.chat_memory.add_user_message(message["output"])
        else:
            memory.chat_memory.add_ai_message(message["output"])

    cl.user_session.set("memory", memory)

    setup_runnable()
    

@cl.on_message
async def on_message(msg: cl.Message):
    config = {"configurable": {"thread_id": cl.context.session.id}}
    memory = cl.user_session.get("memory")  # type: ConversationBufferMemory
    runnable = cl.user_session.get("runnable")  # type: Runnable

    res = cl.Message(content="")

    stream = runnable.astream(
        {"messages": [HumanMessage(content=msg.content)]},
        stream_mode="messages",
        config=RunnableConfig(
            # callbacks=[cb], # just for tracing langsmith
            memory=memory,
            **config
        )
    )
    async for msg, metadata in stream:
        print(f'{"<*>"*50} \n {str(msg)=} \n {">*<"*50}')
        print(f'{".*."*50} \n {str(metadata)=} \n {".*."*50}')
        
        if (
            msg.content
            and hasattr(msg, "response_metadata")
            and getattr(msg, "response_metadata").get("finish_reason") == "stop"
            # and not isinstance(msg, HumanMessage)
            # and (
            #         (
            #             not metadata.get("langgraph_node", None)
            #             or metadata["langgraph_node"] == "final"
            #         )
            #     or (
            #             not getattr(getattr(msg, "response_metadata", None), "finish_reason", None)
            #             or getattr(msg, "response_metadata")["finish_reason"] == "stop"
            #         )
            # )
        ):
            
            await res.stream_token(msg.content)

    await res.send()

    memory.chat_memory.add_user_message(msg.content)
    memory.chat_memory.add_ai_message(res.content)

    