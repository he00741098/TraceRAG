# src/preprocess/pipeline.py

from src.preprocess import java_code_split, code_cleaning_summarization, store_vector_database, apk_decompile, apk_info_extract
from src.config import load_config, set_env_variables


def preprocess_pipeline(apk_path, collection_name):
    """Split, clean, summarize, and store into Qdrant."""
    config = load_config()

    openai_api_key = config["openai"]["api_key"]
    qdrant_url = config["qdrant"]["url"]
    qdrant_api_key = config["qdrant"]["api_key"]

    java_directory = config["directories"]["java_dir"]

    input_file_split = f"{java_directory}_Split"
    input_file_split_cleaned = f"{java_directory}_Split_Cleaned"
    input_file_split_cleaned_summarized = f"{java_directory}_Split_Cleaned_Summarized"

    # decompile apk to java
    apk_decompile.decompile_apk(apk_path)
    print("Decomplie Success !!")
    apk_info_extract.apk_info_extract(apk_path)

    # split into methods
    java_code_split.split_java_files(java_directory)

    # clean and summarize
    code_cleaning_summarization.clean_java_files(input_file_split, input_file_split_cleaned)
    code_cleaning_summarization.summarize_java_files(input_file_split_cleaned, input_file_split_cleaned_summarized)

    print(f"Code summaries have been saved to: {input_file_split_cleaned_summarized}")

    # store into Qdrant
    store_vector_database.process_java_summaries(
        input_file_split_cleaned,
        input_file_split_cleaned_summarized,
        qdrant_url,
        qdrant_api_key,
        collection_name,
        openai_api_key,
    )
    print("Stored in Qdrant.")
