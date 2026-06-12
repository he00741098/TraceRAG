import os
import time

import openai
from src.config import load_config,set_env_variables
config = load_config()

from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model=config["llm"]["model_name"], temperature = config["llm"]["temperature"], base_url=config["llm"]["base_url"], api_key=config["openai"]["api_key"], max_tokens=8192)
# Tool-call nodes only need a short response (~500 tokens for JSON tool call)
llm_toolcall = ChatOpenAI(model=config["llm"]["model_name"], temperature = config["llm"]["temperature"], base_url=config["llm"]["base_url"], api_key=config["openai"]["api_key"], max_tokens=2048)


def _check_truncation(response, node_name: str):
    """Log a warning if the LLM response was truncated due to token limits."""
    finish_reason = response.response_metadata.get('finish_reason', '')
    if finish_reason == 'length':
        print(f"  [WARN] {node_name}: output TRUNCATED (finish_reason='length'). "
              f"Response may be incomplete.")

from langchain_openai import OpenAIEmbeddings


from qdrant_client import QdrantClient
from qdrant_client.models import Filter as QFilter, FieldCondition, MatchText
# from llama_index.vector_stores.weaviate import WeaviateVectorStore
from llama_index.core import VectorStoreIndex
from llama_index.core.response.pprint_utils import pprint_source_node
# cloud

# max_retries = 5
# retry_count = 0
#
# while retry_count < max_retries:
#     try:
#         client = weaviate.connect_to_wcs(
#             cluster_url=config["weaviate"]["url"],
#             auth_credentials=weaviate.auth.AuthApiKey(config["weaviate"]["api_key"]),
#         )
#         vector_store = WeaviateVectorStore(
#             weaviate_client=client,
#             index_name=config["weaviate"]["index_name"]
#         )
#         break  # Success
#     except Exception as e:
#         retry_count += 1
#         print(f"[Retry {retry_count}/{max_retries}] Connection to Weaviate failed: {e}. Retrying in 3 seconds...")
#         time.sleep(3)
# else:
#     raise RuntimeError(f"Failed to connect to Weaviate after {max_retries} attempts. Please check your configuration.")

client = QdrantClient(url=config["qdrant"]["url"])


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
#Step 1 Decide whether or not trigger retrieve tool
def query_or_respond(state: MessagesState):
    """Generate tool call for retrieval"""

    llm_with_tools = llm_toolcall.bind_tools([retrieve], tool_choice="any")
    response = llm_with_tools.invoke(state["messages"])
    _check_truncation(response, "query_or_respond")
    return {"messages": [response]}

from langchain_core.tools import tool

# Tool. Retrieve using query from Weaviate Vector DataBase
@tool(response_format="content_and_artifact")
@retry(stop=stop_after_attempt(10), wait=wait_fixed(5), retry=tenacity.retry_if_exception_type(Exception))
def retrieve(query: str, method_name: Optional[str]=None, class_name: Optional[str]=None):
    """Retrieve information related to a query.
    The query will be a question about an Android app's Java code.
    `method_metadata` refers to the name of a Java method explicitly present in the seen code and related to the query.
    `class_name` refers to the name of the Java class that may also be relevant for filtering results.
    If either `method_metadata` or `class_name` is not provided, those filters will not be used.
    """
    try:
        # 生成嵌入
        embeddings_query = OpenAIEmbeddings(model=config["llm"]["embedding_model"], base_url=config["llm"]["base_url_embedding"], api_key=config["openai"]["api_key"], check_embedding_ctx_length=False)
        embedding_vector = embeddings_query.embed_query(query)
        # Java_Vec_DB = client.collections.get(config["weaviate"]["index_name"])

        filter_condition = None
        must_conditions = []
        if method_name:
            must_conditions.append(FieldCondition(key="methods", match=MatchText(text=method_name)))
        if class_name:
            must_conditions.append(FieldCondition(key="class", match=MatchText(text=class_name)))
        if must_conditions:
            filter_condition = QFilter(must=must_conditions)

        # 查询向量数据库
        retrieved_docs = client.query_points(
            collection_name = config["qdrant"]["collection_name"],
            query=embedding_vector,
            query_filter = filter_condition,
            limit = config["qdrant"]["retrieve_num_limit"],
            with_payload=True
        ).points

        # 格式化结果
        serialized = "\n\n".join(
            # f"File Path:{obj.properties['file_path']}\nClass Name:{obj.properties['class']}\nContent: {obj.properties['original_code']}"
            f"Package Path:{obj.payload.get('file_path')}\nClass Name:{obj.payload.get('class')}\nContent: {obj.payload.get('original_code')}"
            for obj in retrieved_docs
            if obj.payload and 'original_code' in obj.payload
        )
        docs = [point.model_dump() for point in retrieved_docs]

        return serialized, docs
    except Exception as e:
        raise RuntimeError(f"Query failed after multiple retries: {str(e)}")

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
    file_path_1 = config["conversation_directories"]["user_query_retrieval_save_path"]

    # 确保目标目录存在
    os.makedirs(os.path.dirname(file_path_1), exist_ok=True)

    # 写入文件
    with open(file_path_1, "w", encoding="utf-8") as file:
        file.write(docs_content_re)


    
    #read json to retrieve prompt 
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
    _check_truncation(response, "reorder")
    

    # 获取目标文件路径
    file_path = config["conversation_directories"]["user_query_retrieval_filtered_path"]

    # 确保目标目录存在
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # 写入文件
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(str(response.content))
    
    return {"messages": [response]}


from langgraph.graph import MessagesState, StateGraph
from langgraph.graph import END
from langgraph.prebuilt import ToolNode, tools_condition

graph_builder3 = StateGraph(MessagesState)
graph_builder = graph_builder3

graph_builder.add_node(query_or_respond)
graph_builder.add_node(tools)
graph_builder.add_node(reorder)


graph_builder.set_entry_point("query_or_respond")

graph_builder.add_edge("query_or_respond", "tools")
graph_builder.add_edge("tools", "reorder")



from langgraph.checkpoint.memory import MemorySaver
from datetime import datetime  # 导入 datetime 模块

# 创建 MemorySaver 实例
memory = MemorySaver()

# 编译图并设置检查点
graph = graph_builder.compile(checkpointer=memory)

# 运行流程
def execute_query(input_message: str):
    """执行查询流程，并将结果保存至文件。"""
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
