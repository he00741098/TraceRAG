"""
Run TraceRAG analysis on pre-split source JSONL files.

Usage:
    python -m src.jsonl_pipeline <jsonl_path> <collection_name> [--resume] [--output-dir DIR]

Two JSONL formats are accepted:
1. {"rel_path": "sources/com/package/Class/method", "code": "package ..."}
2. OpenAI batch dumps: {"custom_id": "SHA256/sources/...", "body": {...}}
"""

import os
import sys
import json
import shutil
import yaml
import argparse
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import load_config, set_env_variables

from src.preprocess.code_cleaning_summarization import (
    clean_java_files,
    summarize_java_files,
)
from src.preprocess.store_vector_database import process_java_summaries
from src.conversation.first_phase import execute_query
from src.conversation.first_phase_result_process import split_and_store_java_code
from src.conversation.second_phase import model_conversation
from src.postprocess.combine_single_question_report import question_report_generation
from src.postprocess.txt2markwon_and_html import convert_txt_to_md_and_html
from src.postprocess.Final_report_Generation import apk_report_generation

CONFIG_PATH = "config.yaml"


def update_collection_name(new_collection_name, config_path=CONFIG_PATH):
    """Write the new Qdrant collection name into config.yaml."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["qdrant"]["collection_name"] = new_collection_name
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True)


def persist_config(config_dict, config_path=CONFIG_PATH):
    # conversation modules reload config.yaml, so scoped paths must
    # live on disk, not just in memory
    
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_dict, f, allow_unicode=True)


def ingest_jsonl(jsonl_path, split_dir, resume=False):
    """Read a JSONL file and write each entry's code to the _Split tree."""
    entries_written = 0
    entries_skipped = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [WARN] Skipping malformed JSON line: {e}")
                continue

            # original format or OpenAI batch dump
            if "body" in entry and "custom_id" in entry:
                rel_path = entry.get("custom_id", "")
                try:
                    code = entry["body"]["messages"][1]["content"]
                except (KeyError, IndexError, TypeError):
                    print(f"  [WARN] Batch entry missing code, skipping: {rel_path[:80]}")
                    continue
            else:
                rel_path = entry.get("rel_path", "")
                code = entry.get("code", "")

            if not code or not code.strip():
                continue

            # normalise to <class_path>/<member> (drop SHA and sources/ prefix)
            sources_idx = rel_path.find("/sources/")
            if sources_idx != -1:
                rel_path = rel_path[sources_idx + len("/sources/"):]
            elif rel_path.startswith("sources/"):
                rel_path = rel_path[len("sources/"):]

            out_path = os.path.join(split_dir, rel_path) + ".java"

            if resume and os.path.exists(out_path):
                entries_skipped += 1
                continue

            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as out_f:
                out_f.write(code)
            entries_written += 1

    if entries_skipped:
        print(f"  (resume: skipped {entries_skipped} existing files)")
    return entries_written


def create_minimal_apk_info(sha256, output_path):
    """Write a minimal APK_INFO.txt with just the SHA256."""
    content = f"SHA256: {sha256}\n"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [APK Info] SHA256: {sha256} -> {output_path}")


def run_conversation_pipeline(config, jsonl_path=None):
    """Retrieval + analysis over all question categories."""
    try:
        with open("src/Prompt_and_Question/question_3_category.json", "r", encoding="utf-8") as f:
            questions = json.load(f)
    except Exception as e:
        print(f"Failed to read questions : {str(e)}")
        return

    for question_name, retrieve_q in questions.items():
        sub_questions = retrieve_q.get("questions", [])
        print(f"\n[Category] {question_name} ({len(sub_questions)} sub-questions)")

        # collect all snippets from all sub-questions before analysing
        all_category_snippets = set()

        for retrieve_question in sub_questions:
            print(f"  [Phase 1] Query: {retrieve_question[:80]}...")
            execute_query(retrieve_question)
            split_and_store_java_code()

            code_snippet_path = config["conversation_directories"][
                "user_query_retrieval_filtered_split_path"
            ]
            if not os.path.exists(code_snippet_path):
                continue

            for filename in sorted(os.listdir(code_snippet_path)):
                if filename.endswith(".txt"):
                    file_path = os.path.join(code_snippet_path, filename)
                    with open(file_path, "r", encoding="utf-8") as f:
                        all_category_snippets.add(f.read())

        if not all_category_snippets:
            print("  [Skip] No snippets found for this category.")
            continue

        # run Phase 2 once per category with all snippets batched
        output_dir = config["conversation_directories"]["user_query_analyze_path"]
        os.makedirs(output_dir, exist_ok=True)
        file_contents = []

        print(f"  [Phase 2] Analysing {len(all_category_snippets)} snippets")
        batch_size = 5
        snippet_list = sorted(all_category_snippets)
        total_chunks = (len(snippet_list) + batch_size - 1) // batch_size

        def process_batch(chunk_idx, batch_start, batch):
            combined = ""
            for j, code in enumerate(batch):
                combined += (
                    f"\n\n--- Start of snippet {batch_start + j + 1} ---\n"
                    + code
                    + f"\n--- End of snippet {batch_start + j + 1} ---\n"
                )
            analyze_question = (
                f"Here is a batch of Android app java code snippets about "
                f"{question_name}. Please analyze them together to identify "
                f"any potential malicious behavior."
            )
            chunk_num = chunk_idx + 1
            print(f"  [Phase 2] Batch {chunk_num}/{total_chunks} (started)")
            result = model_conversation(analyze_question, combined)
            chunk_output = os.path.join(
                output_dir, f"batched_analysis_result_chunk_{chunk_num}.txt"
            )
            with open(chunk_output, "w", encoding="utf-8") as out_f:
                out_f.write(str(result))
            print(f"  [Phase 2] Batch {chunk_num}/{total_chunks} (done)")
            return (
                chunk_num,
                f"Batched conversation history (Chunk {chunk_num})\n{str(result)}",
            )

        chunk_results = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for i in range(0, len(snippet_list), batch_size):
                batch = snippet_list[i : i + batch_size]
                chunk_idx = i // batch_size
                futures[executor.submit(process_batch, chunk_idx, i, batch)] = chunk_idx
            for future in as_completed(futures):
                chunk_num, text = future.result()
                chunk_results[chunk_num] = text

        for chunk_num in sorted(chunk_results.keys()):
            file_contents.append(chunk_results[chunk_num])

        combined_file_path = os.path.join(output_dir, "code_report_combined.txt")
        with open(combined_file_path, "w", encoding="utf-8") as combined_f:
            combined_f.write("\n\n".join(file_contents))
        print(f"  [Done] {total_chunks} batches processed for {question_name}.")

        # per-question report
        try:
            final_result = question_report_generation(file_contents)
            final_report_path = os.path.join(output_dir, "question_report.txt")
            with open(final_report_path, "w", encoding="utf-8") as f:
                f.write(final_result)
            print(f"  [Report] {final_report_path}")
            convert_txt_to_md_and_html(final_report_path)
        except Exception as e:
            print(f"  [Error] Failed to run question_report_generation: {e}")

        # move results into the category folder
        try:
            llm_output_base = config["conversation_directories"]["LLM_output"]
            question_output_dir = os.path.join(llm_output_base, question_name)
            os.makedirs(question_output_dir, exist_ok=True)
            for folder_name in ["analyze", "retrieve"]:
                src_folder = os.path.join(llm_output_base, folder_name)
                dst_folder = os.path.join(question_output_dir, folder_name)
                if os.path.exists(src_folder):
                    if os.path.exists(dst_folder):
                        shutil.rmtree(dst_folder)
                    shutil.move(src_folder, dst_folder)
        except Exception as e:
            print(f"  [Error] Failed to move folders: {e}")

    # final APK report
    def collect_question_reports(base_dir):
        final_report = ""
        for category in sorted(os.listdir(base_dir)):
            category_path = os.path.join(base_dir, category)
            question_path = os.path.join(category_path, "analyze", "question_report.txt")
            if os.path.isfile(question_path):
                with open(question_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                final_report += f"{category} Report:\n{content}\n\n"
        return final_report.strip()

    llm_output_base = config["conversation_directories"]["LLM_output"]
    merged = collect_question_reports(llm_output_base)
    if merged:
        apk_result = apk_report_generation(merged)
        output_path = os.path.join(llm_output_base, "APK_Report.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(apk_result)
        convert_txt_to_md_and_html(output_path)
        print(f"\n[Final Report] {output_path}")
    else:
        print("\n[Final Report] No question reports found to aggregate.")


def main():
    set_env_variables()
    config = load_config()

    parser = argparse.ArgumentParser(
        description="Run TraceRAG analysis from pre-split JSONL source code."
    )
    parser.add_argument(
        "jsonl_path",
        type=str,
        help="Path to a .jsonl file or directory of .jsonl files.",
    )
    parser.add_argument(
        "collection_name", type=str, help="Collection name for Qdrant."
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume from the last completed phase."
    )
    parser.add_argument(
        "--skip-preprocess",
        action="store_true",
        help="Skip ingest/clean/summarize/store and run only the analysis phase.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Base output directory (default: output).",
    )
    args = parser.parse_args()

    jsonl_path = args.jsonl_path
    collection_name = args.collection_name
    resume = args.resume
    skip_preprocess = args.skip_preprocess
    output_dir = args.output_dir

    update_collection_name(collection_name)
    config = load_config()

    # scope all output under --output-dir so runs don't collide
    config["directories"]["java_dir"] = f"{output_dir}/reversedAPK/sources"
    config["directories"]["apk_info_dir"] = f"{output_dir}/APK_info.txt"
    config["conversation_directories"]["LLM_output"] = f"{output_dir}/LLM_output"
    config["conversation_directories"]["user_query_analyze_path"] = (
        f"{output_dir}/LLM_output/analyze"
    )
    config["conversation_directories"]["user_query_retrieval_filtered_path"] = (
        f"{output_dir}/LLM_output/retrieve/user_query_retrieve_filtered_result"
    )
    config["conversation_directories"]["user_query_retrieval_filtered_split_path"] = (
        f"{output_dir}/LLM_output/retrieve/split_filtered_result"
    )
    config["conversation_directories"]["user_query_retrieval_save_path"] = (
        f"{output_dir}/LLM_output/retrieve/user_query_retrieve_result"
    )
    persist_config(config)

    java_dir = config["directories"]["java_dir"]
    split_dir = f"{java_dir}_Split"
    cleaned_dir = f"{java_dir}_Split_Cleaned"
    summarized_dir = f"{java_dir}_Split_Cleaned_Summarized"

    # clean out any previous run unless resuming
    if not resume:
        llm_output_dir = config["conversation_directories"]["LLM_output"]
        dirs_to_clear = [llm_output_dir]
        if not skip_preprocess:
            dirs_to_clear += [split_dir, cleaned_dir, summarized_dir]
        for d in dirs_to_clear:
            if os.path.exists(d):
                shutil.rmtree(d)

    os.makedirs(output_dir, exist_ok=True)

    # steps 1-4: ingest, clean, summarize, store
    if not skip_preprocess:
        jsonl_files = []
        if os.path.isfile(jsonl_path) and jsonl_path.endswith(".jsonl"):
            jsonl_files = [jsonl_path]
        elif os.path.isdir(jsonl_path):
            jsonl_files = sorted(Path(jsonl_path).glob("*.jsonl"))

        if not jsonl_files:
            print(f"[Error] No .jsonl files found at {jsonl_path}")
            sys.exit(1)

        total_ingested = 0
        for jf in jsonl_files:
            print(f"[Ingest] {jf}")
            sha = Path(jf).stem.upper()
            if not resume:
                create_minimal_apk_info(sha, config["directories"]["apk_info_dir"])
            total_ingested += ingest_jsonl(str(jf), split_dir, resume=resume)
        print(f"[Ingest] {total_ingested} entries written to {split_dir}")

        print(f"[Cleaning] {split_dir} -> {cleaned_dir}")
        clean_java_files(split_dir, cleaned_dir)

        print(f"[Summarizing] {cleaned_dir} -> {summarized_dir}")
        summarize_java_files(cleaned_dir, summarized_dir)

        print(f"[Storing] into Qdrant collection '{collection_name}'")
        process_java_summaries(
            cleaned_dir,
            summarized_dir,
            config["qdrant"]["url"],
            config["qdrant"]["api_key"],
            collection_name,
            config["openai"]["api_key"],
        )
    else:
        print(f"[Skip] Preprocessing skipped, using Qdrant collection '{collection_name}'")

    # steps 5-6: retrieval, analysis, report
    run_conversation_pipeline(config, jsonl_path=jsonl_path)


if __name__ == "__main__":
    main()
