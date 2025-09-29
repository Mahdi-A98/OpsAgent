from pathlib import Path
from langchain_community.document_loaders import WebBaseLoader, BSHTMLLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langgraph.graph import StateGraph, END
from core.settings import OPENAI_API_KEY, FAISS_INDEX_PATH
from langgraph.graph import MessagesState
from typing import Optional
from core.utils.log_tools import log_wrapper
from core.utils.web_driver import access_chrome_driver


class SearchAgentState(MessagesState):
    # pass
    url: Optional[str]
    query: Optional[str]
    raw_text: Optional[str]
    context_text: Optional[str]
    context: Optional[str]




def powerful_web_loader(url):
    driver = access_chrome_driver()


@log_wrapper# --- Nodes ---
def load_web_content(state):    
    url = state["url"]
    loader = WebBaseLoader(url)
    docs = loader.load()
    text = " ".join(doc.page_content.strip() for doc in docs)
    return {"raw_text": text}

@log_wrapper
def decide_processing(state):    
    """If text is short, skip embedding. Otherwise, go to split/embed."""
    text = state["raw_text"]
    word_count = len(text.split())
    if word_count < 1200:   # 👈 tune threshold based on your model's context
        return "short_text"
    else:
        return "long_text"

@log_wrapper
def split_docs(state):
    print(f"in split docs: {state=}")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100
    )
    chunks = splitter.split_text(state["raw_text"])
    return {"chunks": chunks}

@log_wrapper
def embed_and_store(state):
    embeddings = OpenAIEmbeddings()
    if FAISS_INDEX_PATH.exists():
        # Reuse existing index
        vectorstore = FAISS.load_local(FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
    else:
        # Create and save new index
        vectorstore = FAISS.from_texts(state["chunks"], embeddings)
        vectorstore.save_local(FAISS_INDEX_PATH)
    return {"retriever": vectorstore.as_retriever(search_kwargs={"k": 3})}

@log_wrapper
def retrieve_relevant(state):
    print(f"in retrieve_relevant: {state=}")
    retriever = state["retriever"]
    query = state["query"]
    docs = retriever.get_relevant_documents(query)
    return {"context_text": "\n\n".join(d.page_content for d in docs)}

@log_wrapper
def summarize_short_text(state):    
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    query = state["query"]
    text = state["raw_text"]

    # If short, just summarize + answer directly
    response = llm.predict(
        f"Here is some content:\n\n{text}\n\nAnswer this question based only on the text: {query}"
    )
    return {"answer": response}

@log_wrapper
def summarize_long_text(state):    
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    context = state["context_text"]
    query = state["query"]

    if len(context.split()) > 1500:
        context = llm.predict(f"Summarize in under 500 words:\n\n{context}")

    response = llm.predict(
        f"Answer based only on the following context:\n\n{context}\n\nQuestion: {query}"
    )
    return {"answer": response}

# --- Graph ---
graph = StateGraph(SearchAgentState)

graph.add_node("load", load_web_content)
graph.add_node("split", split_docs)
graph.add_node("embed", embed_and_store)
graph.add_node("retrieve", retrieve_relevant)
graph.add_node("summarize_short", summarize_short_text)
graph.add_node("summarize_long", summarize_long_text)

graph.set_entry_point("load")

# Branching logic
graph.add_conditional_edges("load", decide_processing, {
    "short_text": "summarize_short",
    "long_text": "split"
})

graph.add_edge("split", "embed")
graph.add_edge("embed", "retrieve")
graph.add_edge("retrieve", "summarize_long")
graph.add_edge("summarize_short", END)
graph.add_edge("summarize_long", END)

search_agent= graph.compile()

# --- Run Example ---
if __name__ == "__main__":
    result = search_agent.invoke({
        "url": "https://example.com",
        "query": "What is the main idea of this page?"
    })
    print(result["answer"])
