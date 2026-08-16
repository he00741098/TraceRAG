import sys
import os
import shutil
import json
import argparse
import yaml
from src.config import load_config,set_env_variables

from src.preprocess.pipeline import preprocess_pipeline

# shared with the JSONL pipeline so both behave the same
from src.jsonl_pipeline import run_conversation_pipeline



CONFIG_PATH = r"config.yaml"

def update_collection_name(new_collection_name, config_path=CONFIG_PATH):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # store in Qdrant
    config['qdrant']['collection_name'] = new_collection_name

    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True)


def reset_output_paths(config_path=CONFIG_PATH):
    # put default paths back in config.yaml (the JSONL pipeline leaves
    # scoped ones behind)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    config['directories']['apk_info_dir'] = 'output/APK_info.txt'
    config['directories']['java_dir'] = 'output/reversedAPK/sources'
    config['directories']['reversed_apk_dir'] = 'output/reversedAPK'
    config['conversation_directories']['LLM_output'] = 'output/LLM_output'
    config['conversation_directories']['user_query_analyze_path'] = 'output/LLM_output/analyze'
    config['conversation_directories']['user_query_retrieval_filtered_path'] = 'output/LLM_output/retrieve/user_query_retrieve_filtered_result'
    config['conversation_directories']['user_query_retrieval_filtered_split_path'] = 'output/LLM_output/retrieve/split_filtered_result'
    config['conversation_directories']['user_query_retrieval_save_path'] = 'output/LLM_output/retrieve/user_query_retrieve_result'

    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True)



if __name__ == "__main__":

    set_env_variables()

    # 读取 YAML 配置
    config = load_config()



    parser = argparse.ArgumentParser(description="Run APK analysis pipeline.")
    parser.add_argument("apk_directory", type=str, help="Path to the APK file or directory containing APKs.")
    parser.add_argument("collection_name", type=str, help="Collection name for Qdrant.")
    parser.add_argument(
        "--skip-preprocess",
        action="store_true",
        help="Skip decompile/split/clean/summarize/store and run only the analysis phase.",
    )

    args = parser.parse_args()
    apk_directory = args.apk_directory
    collection_name = args.collection_name
    skip_preprocess = args.skip_preprocess

    # 更新 YAML 文件中的 collection_name
    update_collection_name(collection_name)
    reset_output_paths()

    # 读取更新后的配置
    config = load_config()

    
    # # accept a apk file as input
    # # 1.decompile it to extract java files ### also extract all the apk info like sha256,package name, version from manifest and other
    # # 2.spilt these extracted java file into methods
    # # 3.clean the code to remove obfuscation
    # # 4.generated code description for split and cleaned code snippets/.
    # # 5.store these java code and txt description into vector database to construct RAG
    if skip_preprocess:
        print(f"[Skip] Preprocessing skipped, using Qdrant collection '{collection_name}'")
    else:
        preprocess_pipeline(apk_directory, collection_name)




    # retrieval + analysis + final APK report
    run_conversation_pipeline(config)






    




















