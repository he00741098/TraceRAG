import os
import time

import openai
from src.config import load_config, set_env_variables

from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings

from qdrant_client import QdrantClient
from qdrant_client.models import Filter as QFilter, FieldCondition, MatchText
# from llama_index.vector_stores.weaviate import WeaviateVectorStore
from llama_index.core import VectorStoreIndex
from llama_index.core.response.pprint_utils import pprint_source_node

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
import re
from langgraph.graph import MessagesState, StateGraph
from langchain_core.messages import RemoveMessage
import json
from langsmith import traceable
from tenacity import retry, stop_after_attempt, wait_fixed
import tenacity
from typing import Optional


# Tool. Retrieve using query from Qdrant Vector DataBase
@tool(response_format="content_and_artifact")
@retry(stop=stop_after_attempt(10), wait=wait_fixed(5), retry=tenacity.retry_if_exception_type(Exception))
def retrieve(query: str, method_name: Optional[str]=None, class_name: Optional[str]=None):
    """Retrieve information related to a query.
    The query will be a question about an Android app's Java code.
    `method_metadata` refers to the name of a Java method explicitly present in the seen code and related to the query.
    `class_name` refers to the name of the Java class that may also be relevant for filtering results.
    If either `method_metadata` or `class_name` is not provided, those filters will not be used.
    """
    # Load fresh config at runtime so updated collection_name / settings are picked up
    _config = load_config()
    try:
        # 生成嵌入
        embeddings_query = OpenAIEmbeddings(
            model=_config["llm"]["embedding_model"],
            base_url=_config["llm"]["base_url_embedding"],
            api_key=_config["openai"]["api_key"],
            check_embedding_ctx_length=False
        )
        embedding_vector = embeddings_query.embed_query(query)

        # Create a fresh Qdrant client each call so config changes are honoured
        _client = QdrantClient(url=_config["qdrant"]["url"])

        filter_condition = None
        if method_name and class_name:
            filter_condition = QFilter(must=[
                FieldCondition(key="methods", match=MatchText(text=method_name)),
                FieldCondition(key="class", match=MatchText(text=class_name))
            ])

        # 查询向量数据库
        retrieved_docs = _client.query_points(
            collection_name=_config["qdrant"]["collection_name"],
            query=embedding_vector,
            query_filter=filter_condition,
            limit=_config["qdrant"]["retrieve_num_limit"],
            with_payload=True
        ).points

        # 格式化结果
        serialized = "\n\n".join(
            f"Package Path:{obj.payload.get('file_path')}\nClass Name:{obj.payload.get('class')}\nContent: {obj.payload.get('original_code')}"
            for obj in retrieved_docs
            if obj.payload and 'original_code' in obj.payload
        )
        docs = [point.model_dump() for point in retrieved_docs]

        return serialized, docs
    except Exception as e:
        raise RuntimeError(f"Query failed after multiple retries: {str(e)}")


def execute_query(input_message: str):
    """执行查询流程，并将结果保存至文件。
    Builds the LangGraph runtime from fresh config so collection_name
    and other settings set by main.py (via update_config_index_name) are honoured.
    """
    conf = load_config()

    llm = ChatOpenAI(
        model=conf["llm"]["model_name"],
        temperature=conf["llm"]["temperature"],
        base_url=conf["llm"]["base_url"],
        api_key=conf["openai"]["api_key"]
    )

    # Step 1: Decide whether or not to trigger retrieve tool
    def query_or_respond(state: MessagesState):
        """Generate tool call for retrieval"""
        llm_with_tools = llm.bind_tools([retrieve], tool_choice="any")
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    # Step 2: Execute the retrieval.
    tools = ToolNode([retrieve])

    # Step 3: Generate a response using the retrieved content.
    def reorder(state: MessagesState):
        """Generate answer."""
        # 提取查询内容
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

        # Format into prompt
        docs_content_re = "\n\n".join(doc.content for doc in tool_messages)

        # 获取目标文件路径
        file_path_1 = conf["conversation_directories"]["user_query_retrieval_save_path"]

        # 确保目标目录存在
        os.makedirs(os.path.dirname(file_path_1), exist_ok=True)

        # 写入文件
        with open(file_path_1, "w", encoding="utf-8") as file:
            file.write(docs_content_re)

        # read json to retrieve prompt
        try:
            with open("src/Prompt_and_Question/prompts.json", "r", encoding="utf-8") as f:
                prompts = json.load(f)
        except Exception as e:
            print(f"Failed to read prompts.json : {str(e)}")
            return ""

        # read prompt
        if "reorder" not in prompts:
            print("prompts.json can not found 'reorder' ")
            return ""

        # append java code
        system_message_content = prompts["reorder"] + "Here's the query: \n" + query + "\nHere's the code with path\n" + docs_content_re

        prompt = [SystemMessage(system_message_content)]
        docs_content_re = "\n\n".join(doc.content for doc in tool_messages)

        # Run
        response = llm.invoke(prompt)

        # 获取目标文件路径
        file_path = conf["conversation_directories"]["user_query_retrieval_filtered_path"]

        # 确保目标目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # 写入文件
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(str(response.content))

        return {"messages": [response]}

    # Build the graph
    graph_builder = StateGraph(MessagesState)
    graph_builder.add_node(query_or_respond)
    graph_builder.add_node(tools)
    graph_builder.add_node(reorder)

    graph_builder.set_entry_point("query_or_respond")
    graph_builder.add_edge("query_or_respond", "tools")
    graph_builder.add_edge("tools", "reorder")

    graph = graph_builder.compile()

    # Save graph image
    img_data = graph.get_graph().draw_mermaid_png()
    output_dir_img = "output"
    os.makedirs(output_dir_img, exist_ok=True)
    output_path = os.path.join(output_dir_img, "first_phase_graph.png")
    with open(output_path, "wb") as f:
        f.write(img_data)

    from langgraph.checkpoint.memory import MemorySaver
    from datetime import datetime

    memory = MemorySaver()
    graph = graph_builder.compile(checkpointer=memory)

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
