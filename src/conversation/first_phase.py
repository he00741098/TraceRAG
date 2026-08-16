import os
import time

import openai
from src.config import load_config, set_env_variables

config = load_config()

from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=config["llm"]["model_name"],
    temperature=config["llm"]["temperature"],
    base_url=config["llm"]["base_url"],
    api_key=config["openai"]["api_key"],
)

from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import Filter as QFilter, FieldCondition, MatchText

client = QdrantClient(url=config["qdrant"]["url"])

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.graph import MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver
import json
from tenacity import retry, stop_after_attempt, wait_fixed
import tenacity
from datetime import datetime


# Step 1: decide whether to trigger the retrieval tool
def query_or_respond(state: MessagesState):
    """Generate tool call for retrieval"""
    llm_with_tools = llm.bind_tools([retrieve])
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


# Retrieve from Qdrant using the query embedding
@tool(response_format="content_and_artifact")
@retry(
    stop=stop_after_attempt(10),
    wait=wait_fixed(5),
    retry=tenacity.retry_if_exception_type(Exception),
)
def retrieve(query: str, method_name: str, class_name: str):
    """Retrieve information related to a query.
    The query will be a question about an Android app's Java code.
    `method_name` refers to the name of a Java method explicitly present in
    the seen code and related to the query.
    `class_name` refers to the name of the Java class that may also be
    relevant for filtering results.
    If either `method_name` or `class_name` is not provided, those filters
    will not be used.
    """
    try:
        cfg = load_config()
        embeddings_query = OpenAIEmbeddings(
            model=cfg["llm"]["embedding_model"],
            base_url=cfg["llm"]["base_url_embedding"],
            api_key=cfg["openai"]["api_key"],
            check_embedding_ctx_length=False,
        )
        embedding_vector = embeddings_query.embed_query(query)

        filter_condition = None
        if method_name and class_name:
            filter_condition = QFilter(
                must=[
                    FieldCondition(key="methods", match=MatchText(text=method_name)),
                    FieldCondition(key="class", match=MatchText(text=class_name)),
                ]
            )

        retrieved_docs = client.query_points(
            collection_name=cfg["qdrant"]["collection_name"],
            query=embedding_vector,
            query_filter=filter_condition,
            limit=cfg["qdrant"]["retrieve_num_limit"],
            with_payload=True,
        ).points

        serialized = "\n\n".join(
            f"Package Path:{obj.payload.get('file_path')}\n"
            f"Class Name:{obj.payload.get('class')}\n"
            f"Content: {obj.payload.get('original_code')}"
            for obj in retrieved_docs
            if obj.payload and "original_code" in obj.payload
        )
        docs = [point.model_dump() for point in retrieved_docs]

        return serialized, docs
    except Exception as e:
        raise RuntimeError(f"Query failed after multiple retries: {str(e)}")


# Step 2: execute the retrieval
tools = ToolNode([retrieve])


# Step 3: filter and reorder the retrieved snippets
def reorder(state: MessagesState):
    """Filter and rank retrieved snippets by relevance and risk."""
    for message in state["messages"]:
        if message.type == "human":
            query = message.content

    recent_tool_messages = []
    for message in reversed(state["messages"]):
        if message.type == "tool":
            recent_tool_messages.append(message)
        else:
            break
    tool_messages = recent_tool_messages[::-1]

    docs_content_re = "\n\n".join(doc.content for doc in tool_messages)

    # save raw retrieval results
    cfg = load_config()
    file_path_1 = cfg["conversation_directories"]["user_query_retrieval_save_path"]
    os.makedirs(os.path.dirname(file_path_1), exist_ok=True)
    with open(file_path_1, "w", encoding="utf-8") as file:
        file.write(docs_content_re)

    try:
        with open("src/Prompt_and_Question/prompts.json", "r", encoding="utf-8") as f:
            prompts = json.load(f)
    except Exception as e:
        print(f"Failed to read prompts.json : {str(e)}")
        return ""

    if "reorder" not in prompts:
        print("prompts.json can not found 'reorder' ")
        return ""

    system_message_content = (
        prompts["reorder"]
        + "Here's the query: \n"
        + query
        + "\nHere's the code with path\n"
        + docs_content_re
    )

    prompt = [SystemMessage(system_message_content)]

    response = llm.invoke(prompt)

    # save filtered result
    file_path = cfg["conversation_directories"]["user_query_retrieval_filtered_path"]
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(str(response.content))

    return {"messages": [response]}


graph_builder = StateGraph(MessagesState)

graph_builder.add_node(query_or_respond)
graph_builder.add_node(tools)
graph_builder.add_node(reorder)

graph_builder.set_entry_point("query_or_respond")
graph_builder.add_edge("query_or_respond", "tools")
graph_builder.add_edge("tools", "reorder")

graph = graph_builder.compile()

output_dir = "output"
os.makedirs(output_dir, exist_ok=True)

img_data = graph.get_graph().draw_mermaid_png()
with open(os.path.join(output_dir, "first_phase_graph.png"), "wb") as f:
    f.write(img_data)

memory = MemorySaver()
graph = graph_builder.compile(checkpointer=memory)


def execute_query(input_message: str):
    """Run the retrieval flow and save results."""
    current_time = "Experiment_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    config = {"configurable": {"thread_id": current_time}, "recursion_limit": 25}
    final_result = ""

    for step in graph.stream(
        {"messages": [{"role": "user", "content": input_message}]},
        stream_mode="values",
        config=config,
    ):
        step["messages"][-1].pretty_print()
        final_result += str(step["messages"][-1]) + "\n"

    return final_result
