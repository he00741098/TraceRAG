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
from src.config import load_config

RAW_CODE_EMBED_CHARS = 2000


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

    # 连接 Weaviate 向量数据库
    # client = weaviate.connect_to_wcs(
    #     cluster_url=weaviate_url,
    #     auth_credentials=weaviate.auth.AuthApiKey(weaviate_api_key),
    # )

    max_retries = 5
    retry_count = 0
    client = QdrantClient(url=weaviate_url)

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
            if not filename.endswith(".txt"):
                continue
            # Skip macOS resource forks and .DS_Store
            if filename.startswith("._") or filename == ".DS_Store":
                continue

            logger.info(f"Processing file: {filename}")

            method_name = filename[:-4]  # strip .txt extension
            summary_file_path = os.path.join(root, filename)

            # Build the corresponding .java path by computing the relative
            # path from summary_directory and joining with java_directory.
            # This avoids the naive .replace(".txt", ".java") which breaks
            # when directory names or filenames contain "txt" / "java".
            rel_path = os.path.relpath(summary_file_path, summary_directory)
            java_rel_path = rel_path[:-4] + ".java"  # safe: we know it ends with .txt
            full_java_file_path = os.path.join(java_directory, java_rel_path)

            if not os.path.isfile(full_java_file_path):
                logger.warning(f"Java file not found, skipping: {full_java_file_path}")
                continue

            # 计算 Java 文件相对于 java_directory 的相对路径
            java_file_path = os.path.relpath(full_java_file_path, java_directory)

            # 转换为 FQCN 格式
            if java_file_path.startswith("sources" + os.sep):
                java_file_path = java_file_path[len("sources" + os.sep):]  # 去掉 "sources/" 前缀
            
            fqcn_path = java_file_path.replace(os.sep, ".").replace(".java", "")  # 转换为 FQCN

            # 读取摘要文件内容
            with open(summary_file_path, 'r', encoding='utf-8') as summary_file:
                summary_content = summary_file.read()

            # 读取 Java 代码
            with open(full_java_file_path, 'r', encoding='utf-8') as java_file:
                original_code = java_file.read()

            embedding_text = (
                summary_content
                + "\n\n--- Raw code excerpt ---\n"
                + original_code[:RAW_CODE_EMBED_CHARS]
            )

            # 提取 class 名称（Java 文件所在的文件夹名）
            class_name = os.path.basename(os.path.dirname(full_java_file_path))

            # 创建 TextNode，并存储 metadata
            node = TextNode(
                text=embedding_text,
                metadata={
                    "original_code": original_code,  # 存入 Java 代码
                    "methods": method_name,  # 存入方法名
                    "file_path": fqcn_path,  # 存入 FQCN 格式的 Java 文件路径
                    "class": class_name  # 存入 class 信息
                }
            )
            nodes.append(node)
    
    cfg = load_config()
    Settings.embed_model = OpenAIEmbedding(api_base=cfg["llm"]["base_url_embedding"], api_key=cfg["openai"]["api_key"], model=cfg["llm"]["embedding_model"])
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
