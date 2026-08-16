from langgraph.graph import MessagesState, StateGraph
from langgraph.graph import END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import SystemMessage
import json
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from langchain_core.tools import tool
from qdrant_client import QdrantClient
from qdrant_client.models import Filter as QFilter, FieldCondition, MatchText
import os
import time
import tenacity
from tenacity import retry, stop_after_attempt, wait_fixed

from src.config import load_config, set_env_variables

config = load_config()

llm = ChatOpenAI(
    model=config["llm"]["model_name"],
    temperature=config["llm"]["temperature"],
    base_url=config["llm"]["base_url"],
    api_key=config["openai"]["api_key"],
)
llm_analysis = ChatOpenAI(
    model=config["llm"]["analysis_model"],
    base_url=config["llm"]["base_url"],
    api_key=config["openai"]["api_key"],
)

client = QdrantClient(url=config["qdrant"]["url"])


def _dedup_tail_ai(messages: list):
    # llama.cpp rejects prompts ending with 2+ assistant messages
    while (
        len(messages) >= 2
        and messages[-1].type == "ai"
        and messages[-2].type == "ai"
    ):
        messages.pop(-2)
    return messages


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
        # reload config so we always use the current collection name
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


tools = ToolNode([retrieve])


# filter and rank retrieved code for the current follow-up query
def reorder_for_graph_2(state: MessagesState):
    """Keep only the most relevant snippet."""
    query = ""
    for message in state["messages"]:
        if (
            hasattr(message, "additional_kwargs")
            and "tool_calls" in message.additional_kwargs
        ):
            for tool_call in message.additional_kwargs["tool_calls"]:
                arguments = json.loads(tool_call["function"]["arguments"])
                query = arguments.get("query", None)

    recent_tool_messages = []
    for message in reversed(state["messages"]):
        if message.type == "tool":
            recent_tool_messages.append(message)
        else:
            break
    tool_messages = recent_tool_messages[::-1]

    docs_content_re = "\n\n".join(doc.content for doc in tool_messages)

    try:
        with open("src/Prompt_and_Question/prompts.json", "r", encoding="utf-8") as f:
            prompts = json.load(f)
    except Exception as e:
        print(f"Failed to read prompts.json : {str(e)}")
        return ""

    if "reorder_for_graph_2" not in prompts:
        print("prompts.json can not found 'reorder_for_graph_2' ")
        return ""

    system_message_content = (
        prompts["reorder_for_graph_2"]
        + "Here's the query: \n"
        + query
        + "\nHere's the code with path\n"
        + docs_content_re
    )

    prompt = [SystemMessage(system_message_content)]

    response = llm.invoke(prompt)

    return {"messages": [response]}


# main analysis step
def generate(state: MessagesState):
    """Generate answer."""
    recent_tool_messages = []
    for message in reversed(state["messages"]):
        if message.type == "tool":
            recent_tool_messages.append(message)
        else:
            break
    tool_messages = recent_tool_messages[::-1]

    docs_content = "\n\n".join(doc.content for doc in tool_messages)

    try:
        with open("src/Prompt_and_Question/prompts.json", "r", encoding="utf-8") as f:
            prompts = json.load(f)
    except Exception as e:
        print(f"Failed to read prompts.json : {str(e)}")
        return ""

    if "generate" not in prompts:
        print("prompts.json can not found 'generate' ")
        return ""

    system_message_content = prompts["generate"] + "Here's the code: \n" + docs_content

    conversation_messages = [
        message
        for message in state["messages"]
        if message.type in ("human", "system")
        or (message.type == "ai" and not message.tool_calls)
    ]
    # recent history only
    prompt = [SystemMessage(system_message_content)] + _dedup_tail_ai(
        conversation_messages[-8:]
    )

    response = llm_analysis.invoke(prompt)
    return {"messages": [response]}


# Step 4: go back to RAG or output the response
def back_or_output(state: MessagesState):
    """Call the tool when a question was generated by your upstream."""
    try:
        with open("src/Prompt_and_Question/prompts.json", "r", encoding="utf-8") as f:
            prompts = json.load(f)
    except Exception as e:
        print(f"Failed to read prompts.json : {str(e)}")
        return ""

    if "back_or_output" not in prompts:
        print("prompts.json can not found 'back_or_output' ")
        return ""

    system_message_content = prompts["back_or_output"]

    conversation_messages = [
        message
        for message in reversed(state["messages"])
        if message.type == "ai"
    ][0:1]

    prompt = [SystemMessage(system_message_content)] + conversation_messages

    llm_with_tools = llm.bind_tools([retrieve])
    response = llm_with_tools.invoke(prompt)
    return {"messages": [response]}


def report_generator(state: MessagesState):
    """Generate report based on the whole process."""
    try:
        with open("src/Prompt_and_Question/prompts.json", "r", encoding="utf-8") as f:
            prompts = json.load(f)
    except Exception as e:
        print(f"Failed to read prompts.json : {str(e)}")
        return ""

    if "report_generator" not in prompts:
        print("prompts.json can not found 'report_generator' ")
        return ""

    system_message_content = prompts["report_generator"]

    conversation_messages = [
        message
        for message in state["messages"]
        if message.type in ("human", "system")
        or (message.type == "ai" and not message.tool_calls)
    ]

    # recent history only
    prompt = [SystemMessage(system_message_content)] + _dedup_tail_ai(
        conversation_messages[-12:]
    )

    cfg = load_config()
    output_dir = cfg["conversation_directories"]["user_query_analyze_path"]
    os.makedirs(output_dir, exist_ok=True)

    # save the analysis details for later inspection
    output_file_1 = os.path.join(output_dir, "Detail.txt")
    with open(output_file_1, "w", encoding="utf-8") as file:
        for msg in conversation_messages:
            file.write(msg.content + "\n\n")

    response = llm.invoke(prompt)

    return {"messages": [response]}


graph_builder1 = StateGraph(MessagesState)

graph_builder1.add_node(tools)
graph_builder1.add_node(generate)
graph_builder1.add_node(back_or_output)
graph_builder1.add_node(reorder_for_graph_2)
graph_builder1.add_node(report_generator)

graph_builder1.set_entry_point("generate")
graph_builder1.add_edge("tools", "reorder_for_graph_2")
graph_builder1.add_edge("reorder_for_graph_2", "generate")
graph_builder1.add_edge("generate", "back_or_output")


def back_or_output_condition(state: MessagesState):
    """Decide whether to retrieve more code or write the report."""
    # stop local models looping forever
    MAX_RETRIEVAL_ROUNDS = 16
    tool_count = sum(
        1 for m in state["messages"] if hasattr(m, "type") and m.type == "tool"
    )
    if tool_count >= MAX_RETRIEVAL_ROUNDS:
        return "generate_report"

    conversation_messages = [
        message
        for message in reversed(state["messages"])
        if message.type == "ai"
    ][0:1]

    if not conversation_messages:
        return "generate_report"

    message = conversation_messages[0]

    if "tool_calls" not in message.additional_kwargs:
        return "generate_report"
    else:
        return "back_to_retrieve"


graph_builder1.add_conditional_edges(
    "back_or_output",
    back_or_output_condition,
    {"back_to_retrieve": "tools", "generate_report": "report_generator"},
)

from langgraph.checkpoint.memory import MemorySaver
from datetime import datetime

memory1 = MemorySaver()
graph1 = graph_builder1.compile(checkpointer=memory1)

output_dir = "output"
os.makedirs(output_dir, exist_ok=True)

img_data = graph1.get_graph().draw_mermaid_png()
with open(os.path.join(output_dir, "second_phase_graph.png"), "wb") as f:
    f.write(img_data)


def model_conversation(input_message, code_snippet):
    """Run the analysis conversation and return the final report."""
    input_message += "\n" + code_snippet

    current_time = "Conversation " + datetime.now().strftime("%Y%m%d_%H%M%S")
    config = {"configurable": {"thread_id": current_time}, "recursion_limit": 50}

    for step in graph1.stream(
        {"messages": [{"role": "user", "content": input_message}]},
        stream_mode="values",
        config=config,
    ):
        step["messages"][-1].pretty_print()
        last_message = step["messages"][-1].content

    return last_message
