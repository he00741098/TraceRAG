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


def process_java_summaries(
    java_directory,
    summary_directory,
    vector_db_url,
    vector_db_api_key,
    collection_name,
    openai_api_key,
):
    """Embed the summaries and their source code into Qdrant."""

    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    logger = logging.getLogger(__name__)

    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key

    client = QdrantClient(url=vector_db_url)

    nodes = []
    logger.info("Starting to process summary files.")

    for root, dirs, files in os.walk(summary_directory):
        for filename in files:
            if not filename.endswith(".txt"):
                continue
            if filename.startswith("._") or filename == ".DS_Store":
                continue

            logger.info(f"Processing file: {filename}")

            method_name = filename[:-4]
            summary_file_path = os.path.join(root, filename)

            # find the matching .java file
            rel_path = os.path.relpath(summary_file_path, summary_directory)
            java_rel_path = rel_path[:-4] + ".java"
            full_java_file_path = os.path.join(java_directory, java_rel_path)

            if not os.path.isfile(full_java_file_path):
                logger.warning(f"Java file not found, skipping: {full_java_file_path}")
                continue

            java_file_path = os.path.relpath(full_java_file_path, java_directory)

            if java_file_path.startswith("sources" + os.sep):
                java_file_path = java_file_path[len("sources" + os.sep):]

            fqcn_path = java_file_path.replace(os.sep, ".").replace(".java", "")

            with open(summary_file_path, "r", encoding="utf-8") as summary_file:
                summary_content = summary_file.read()

            with open(full_java_file_path, "r", encoding="utf-8") as java_file:
                original_code = java_file.read()

            class_name = os.path.basename(os.path.dirname(full_java_file_path))

            # embed summary + raw code head so API names stay searchable
            node = TextNode(
                text=summary_content + "\n\n--- Raw code excerpt ---\n" + original_code[:2000],
                metadata={
                    "original_code": original_code,
                    "methods": method_name,
                    "file_path": fqcn_path,
                    "class": class_name,
                },
            )
            nodes.append(node)

    cfg = load_config()
    Settings.embed_model = OpenAIEmbedding(
        api_base=cfg["llm"]["base_url_embedding"],
        api_key=cfg["openai"]["api_key"],
        model=cfg["llm"]["embedding_model"],
    )
    test_embed = Settings.embed_model.get_text_embedding("test initialization")
    dim_size = len(test_embed)
    if not client.collection_exists(collection_name=collection_name):
        logger.info(f"Collection '{collection_name}' not found. Creating it...")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=dim_size, distance=models.Distance.COSINE
            ),
        )

    vector_store = QdrantVectorStore(client=client, collection_name=collection_name)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    logger.info("Creating vector index and storing on disk.")
    index = VectorStoreIndex(nodes, storage_context=storage_context)
    logger.info("Vector index created and stored.")

    return index
