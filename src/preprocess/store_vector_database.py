import logging
import sys
import os
import time
import openai
from qdrant_client import QdrantClient, models
from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core.schema import TextNode
from llama_index.embeddings.openai import OpenAIEmbedding

    
def process_java_summaries(
    java_directory,
    summary_directory,
    weaviate_url,
    weaviate_api_key,
    index_name,
    openai_api_key
):
    """处理 Java 代码摘要，并存入 Weaviate 向量数据库"""

    # 设置日志
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    logger = logging.getLogger(__name__)

    # 设置 OpenAI API Key
    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key # Deprecated apparently

    max_retries = 5
    retry_count = 0
    client = QdrantClient(url=weaviate_url)

    # Compute the raw (pre-cleaning) java directory.
    # Pipeline produces:
    #   sources_Split/             (raw split code, NOT cleaned)
    #   sources_Split_Cleaned/     (java_directory — cleaned code)
    #   sources_Split_Cleaned_Summarized/  (summary_directory — summaries)
    # We want the original pre-cleaning code for the payload.
    raw_java_directory = java_directory.replace("_Split_Cleaned", "_Split")

    # while retry_count < max_retries:
    #     try:
    #         client = qdrant_client(url=config["qdrant"]["url"])
    #         break  # Success
    #     except Exception as e:
    #         retry_count += 1
    #         print(f"[Retry {retry_count}/{max_retries}] Connection to Weaviate failed: {e}. Retrying in 3 seconds...")
    #         time.sleep(3)
    # else:
    #     raise RuntimeError(f"Failed to connect to Weaviate after {max_retries} attempts. Please check your configuration.")

    nodes = []
    logger.info("Starting to process summary files.")

    
    for root, dirs, files in os.walk(summary_directory):
        for filename in files:
            if filename.endswith(".txt"):  # 处理 .txt 摘要文件
                logger.info(f"Processing file: {filename}")

                method_name = filename.replace(".txt", "")  # 获取方法名
                summary_file_path = os.path.join(root, filename)

                # 构建 Java 文件的完整路径（使用原始未清洗的代码）
                full_java_file_path = summary_file_path.replace(summary_directory, raw_java_directory).replace(".txt", ".java")

                # Also compute the cleaned path (for reading if raw doesn't exist)
                cleaned_java_path = summary_file_path.replace(summary_directory, java_directory).replace(".txt", ".java")

                # 计算 Java 文件相对于原始代码目录的相对路径（用于 FQCN）
                java_file_path = os.path.relpath(full_java_file_path, raw_java_directory)

                # 转换为 FQCN 格式
                if java_file_path.startswith("sources" + os.sep):
                    java_file_path = java_file_path[len("sources" + os.sep):]  # 去掉 "sources/" 前缀
                
                fqcn_path = java_file_path.replace(os.sep, ".").replace(".java", "")  # 转换为 FQCN

                # 读取摘要文件内容
                with open(summary_file_path, 'r', encoding='utf-8') as summary_file:
                    summary_content = summary_file.read()

                # 读取 Java 代码（优先使用原始未清洗的代码）
                code_path = full_java_file_path
                if not os.path.exists(code_path):
                    code_path = cleaned_java_path
                    logger.warning(f"Raw code not found at {full_java_file_path}, falling back to cleaned version")
                with open(code_path, 'r', encoding='utf-8') as java_file:
                    original_code = java_file.read()

                # 提取 class 名称（Java 文件所在的文件夹名）
                class_name = os.path.basename(os.path.dirname(full_java_file_path))

                # 创建 TextNode，并存储 metadata
                # Embed both the LLM summary AND a truncated copy of the raw code.
                # The summary gives semantic understanding; the raw code provides
                # exact API keywords (TelephonyManager.getDeviceId, etc.) that
                # are critical for vector search to match category queries.
                embedded_text = summary_content + "\n\n" + original_code[:800]
                node = TextNode(
                    text=embedded_text,  # 存入摘要 + raw code keywords
                    metadata={
                        "original_code": original_code,  # 存入 Java 代码
                        "methods": method_name,  # 存入方法名
                        "file_path": fqcn_path,  # 存入 FQCN 格式的 Java 文件路径
                        "class": class_name  # 存入 class 信息
                    }
                )
                nodes.append(node)
    
    Settings.embed_model = OpenAIEmbedding(api_base="http://localhost:5002/v1", api_key="sk-local", model="text-embedding-ada-002")
    test_embed = Settings.embed_model.get_text_embedding("test initialization")
    dim_size = len(test_embed)
    if not client.collection_exists(collection_name=index_name):
        logger.info(f"Collection '{index_name}' not found. Creating it manually...")
        client.create_collection(
            collection_name=index_name,
            vectors_config=models.VectorParams(
                size=dim_size, 
                distance=models.Distance.COSINE
            )
        )


    # 存储到 Weaviate 数据库
    vector_store = QdrantVectorStore(client=client, collection_name=index_name)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    logger.info("Creating vector index and storing on disk.")
    index = VectorStoreIndex(nodes, storage_context=storage_context)
    logger.info("Vector index created and stored.")
    
    return index
