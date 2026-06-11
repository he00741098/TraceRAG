"""
JSONL ingestion pipeline for TraceRAG.

Reads pre-split Java source code from JSONL files (as produced by the original
TraceRAG pipeline) and runs the full analysis pipeline on them.

Usage:
    python -m src.jsonl_pipeline <jsonl_path> <index_name>

    jsonl_path: A single .jsonl file or a directory of .jsonl files.
    index_name: Name for the Qdrant collection (replaces config.yaml value).

Each JSONL line has the format:
    {"rel_path": "sources/com/package/Class/method", "code": "package ..."}

The pipeline:
    1. Ingests JSONL entries → writes .java files to reversedAPK/sources_Split/
    2. Generates APK_INFO.txt (SHA256 from filename)
    3. Cleans code with LLM  (→ sources_Split_Cleaned/)
    4. Summarizes with LLM    (→ sources_Split_Cleaned_Summarized/)
    5. Stores in Qdrant
    6. Runs the multi-question retrieval & analysis
    7. Generates final report

Steps 1-2 replace apk_decompile + apk_info_extract + java_code_split since
the JSONL data is already decompiled and split.
"""

import os
import sys
import json
import shutil
import yaml
import argparse
from pathlib import Path

from src.config import load_config, set_env_variables

# Preprocessing
from src.preprocess.code_cleaning_summarization import clean_java_files, summarize_java_files
from src.preprocess.store_vector_database import process_java_summaries

# Conversation & postprocessing
from src.conversation.first_phase import execute_query
from src.conversation.first_phase_result_precess import split_and_store_java_code
from src.conversation.second_phase import model_conversation
from src.postprocess.combine_single_question_report import quesiton_report_generation
from src.postprocess.txt2markwon_and_html import convert_txt_to_md_and_html
from src.postprocess.Final_report_Generation import apk_report_generation

CONFIG_PATH = r"config.yaml"


def update_config_index_name(new_index_name, config_path=CONFIG_PATH):
    """Update the Qdrant collection name in config.yaml."""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    config['qdrant']['collection_name'] = new_index_name
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True)


def ingest_jsonl(jsonl_path, split_dir, resume=False):
    """
    Read one JSONL file and write each entry's code to the _Split directory.

    Each JSONL line has {"rel_path": "...", "code": "..."}.
    Two path formats are supported:
      - "sources/com/package/Class/method"           (benign files)
      - "SHA256/sources/com/package/Class/method"    (malicious files)
    The output path is always split_dir/<class_path>/<member>.java
    (without any SHA prefix and without 'sources/' prefix).

    If resume=True, skip entries whose output file already exists.
    """
    entries_written = 0
    entries_skipped = 0
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [WARN] Skipping malformed JSON line: {e}")
                continue

            rel_path = entry.get("rel_path", "")
            code = entry.get("code", "")

            # Strip SHA256 prefix and/or 'sources/' prefix to normalise
            # the path to just <class_path>/<member_name>
            sources_idx = rel_path.find("/sources/")
            if sources_idx != -1:
                rel_path = rel_path[sources_idx + len("/sources/"):]
            elif rel_path.startswith("sources/"):
                rel_path = rel_path[len("sources/"):]

            # Build output path: split_dir/<rel_path>.java
            out_path = os.path.join(split_dir, rel_path) + ".java"

            if resume and os.path.exists(out_path):
                entries_skipped += 1
                continue

            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            with open(out_path, 'w', encoding='utf-8') as out_f:
                out_f.write(code)
            entries_written += 1

    if entries_skipped:
        print(f"  (resume: skipped {entries_skipped} existing files)")
    return entries_written


def create_minimal_apk_info(sha256, output_path):
    """Create a minimal APK_INFO.txt from just the SHA256 hash."""
    content = (
        f"SHA256: {sha256}\n"
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  [APK Info] SHA256: {sha256} → {output_path}")


def run_conversation_pipeline(config):
    """Run the multi-question retrieval, analysis, and report generation."""
    # Load questions
    try:
        with open("src/Prompt_and_Question/question_3_category.json", "r", encoding="utf-8") as f:
            questions = json.load(f)
    except Exception as e:
        print(f"[Error] Failed to read questions: {e}")
        return

    for question_name, retrieve_q in questions.items():
        for retrieve_question in retrieve_q.get("questions", []):
            print(f"\n[Processing] {question_name}")
            try:
                code_snippet_path = config["conversation_directories"]["user_query_retrieval_filtered_split_path"]
                if os.path.exists(code_snippet_path):
                    shutil.rmtree(code_snippet_path)
                os.makedirs(code_snippet_path, exist_ok=True)

                # Phase 1: Retrieve code from Qdrant
                execute_query(retrieve_question)
                split_and_store_java_code()

                output_dir = config["conversation_directories"]["user_query_analyze_path"]
                os.makedirs(output_dir, exist_ok=True)

                file_contents = []

                if not os.path.exists(code_snippet_path):
                    print(f"  [Error] Path '{code_snippet_path}' does not exist.")
                else:
                    all_files = [f for f in sorted(os.listdir(code_snippet_path)) if f.endswith(".txt")]
                    if not all_files:
                        print(f"  [Skip] No snippets found for {question_name}.")
                        total_chunks = 0
                    else:
                        batch_size = 5
                        for i in range(0, len(all_files), batch_size):
                            batch_files = all_files[i:i + batch_size]
                            combined_snippets = ""

                            for filename in batch_files:
                                file_path = os.path.join(code_snippet_path, filename)
                                try:
                                    with open(file_path, 'r', encoding='utf-8') as f:
                                        combined_snippets += f"\n\n--- Start of {filename} ---\n"
                                        combined_snippets += f.read()
                                        combined_snippets += f"\n--- End of {filename} ---\n"
                                except Exception as e:
                                    print(f"  [Warn] Failed to read {filename}: {e}")

                            if combined_snippets.strip():
                                analyze_question = (
                                    "Here is a batch of Android app java code snippets about "
                                    + question_name
                                    + ". Please analyze them together to identify any potential malicious behavior."
                                )
                                chunk_num = (i // batch_size) + 1
                                total_chunks = (len(all_files) + batch_size - 1) // batch_size
                                print(f"  [Phase 2] Batch {chunk_num}/{total_chunks}")

                                result = model_conversation(analyze_question, combined_snippets)
                                file_contents.append(
                                    f"Batched conversation history (Chunk {chunk_num})\n{str(result)}"
                                )

                                chunk_output_file = os.path.join(output_dir, f'batched_analysis_result_chunk_{chunk_num}.txt')
                                with open(chunk_output_file, 'w', encoding='utf-8') as out_f:
                                    out_f.write(str(result))

                        # Combined report
                        combined_file_path = os.path.join(output_dir, 'code_report_combined.txt')
                        with open(combined_file_path, 'w', encoding='utf-8') as combined_f:
                            combined_f.write("\n\n".join(file_contents))
                        print(f"  [Done] {total_chunks} batches processed for {question_name}.")

                # Generate question report
                if file_contents:
                    try:
                        final_result = quesiton_report_generation(file_contents)
                        final_report_path = os.path.join(output_dir, 'question_report.txt')
                        with open(final_report_path, 'w', encoding='utf-8') as f:
                            f.write(final_result)
                        print(f"  [Report Saved] {final_report_path}")
                        convert_txt_to_md_and_html(final_report_path)
                    except Exception as e:
                        print(f"  [Error] report generation: {e}")

                # Move folders
                try:
                    llm_output_base = config["conversation_directories"]["LLM_output"]
                    question_output_dir = os.path.join(llm_output_base, question_name)
                    os.makedirs(question_output_dir, exist_ok=True)
                    for folder_name in ['analyze', 'retrieve']:
                        src = os.path.join(llm_output_base, folder_name)
                        dst = os.path.join(question_output_dir, folder_name)
                        if os.path.exists(src):
                            if os.path.exists(dst):
                                shutil.rmtree(dst)
                            shutil.move(src, dst)
                except Exception as e:
                    print(f"  [Error] moving folders: {e}")

            except Exception as e:
                print(f"  [Error] processing {question_name}: {e}")

    # Final APK report
    def collect_question_reports(base_dir):
        final_report = ""
        for category in os.listdir(base_dir):
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

    parser = argparse.ArgumentParser(description="Run TraceRAG analysis from pre-split JSONL source code.")
    parser.add_argument("jsonl_path", type=str, help="Path to a .jsonl file or directory of .jsonl files.")
    parser.add_argument("index_name", type=str, help="Index name for the Qdrant vector database.")
    parser.add_argument("--resume", action="store_true", help="Resume from the last completed phase.")
    args = parser.parse_args()

    jsonl_path = args.jsonl_path
    index_name = args.index_name
    resume = args.resume

    # Update config with the new index name
    update_config_index_name(index_name)
    config = load_config()

    java_dir = config["directories"]["java_dir"]                    # output/reversedAPK/sources
    split_dir = f"{java_dir}_Split"                                 # output/reversedAPK/sources_Split
    cleaned_dir = f"{java_dir}_Split_Cleaned"                        # output/reversedAPK/sources_Split_Cleaned
    summarized_dir = f"{java_dir}_Split_Cleaned_Summarized"          # output/reversedAPK/sources_Split_Cleaned_Summarized

    # Clean out any previous run (unless resuming)
    if not resume:
        for d in [split_dir, cleaned_dir, summarized_dir]:
            if os.path.exists(d):
                shutil.rmtree(d)

    # ── Step 1: Ingest JSONL entries into _Split directory ──────────
    jsonl_files = []
    if os.path.isfile(jsonl_path) and jsonl_path.endswith(".jsonl"):
        jsonl_files = [jsonl_path]
    elif os.path.isdir(jsonl_path):
        jsonl_files = sorted(
            [os.path.join(jsonl_path, f) for f in os.listdir(jsonl_path) if f.endswith(".jsonl")]
        )
    else:
        print(f"[Error] Invalid jsonl_path: {jsonl_path}. Must be a .jsonl file or directory of .jsonl files.")
        sys.exit(1)

    print(f"\n{'='*60}")

    # Determine which phases need to run
    ingest_needed = not os.path.exists(split_dir) or any(not os.listdir(split_dir) for _ in [1])
    if resume and not ingest_needed:
        ingest_needed = False

    # ── Step 1: Ingest ──
    if not resume or ingest_needed or True:  # Always try ingest (it skips existing files in resume mode)
        print(f"Ingesting {len(jsonl_files)} JSONL file(s) into: {split_dir}")
        print(f"{'='*60}")

        total_entries = 0
        os.makedirs(split_dir, exist_ok=True)
        for jf in jsonl_files:
            sha256 = Path(jf).stem.upper()
            entries = ingest_jsonl(jf, split_dir, resume=resume)
            total_entries += entries
            print(f"  {Path(jf).name}: {entries} entries ingested")

            # Create APK_INFO.txt
            apk_info_path = config["directories"]["apk_info_dir"]
            create_minimal_apk_info(sha256, apk_info_path)

        print(f"\nTotal: {total_entries} code entries from {len(jsonl_files)} file(s)")
        print(f"Output directory: {split_dir}")

    # ── Step 2: Code cleaning via LLM ──────────
    cleaning_done = os.path.exists(cleaned_dir) and any(os.scandir(cleaned_dir))
    if resume and cleaning_done:
        print(f"\n[Resume] Cleaning phase already complete. Skipping.")
    else:
        print(f"\n{'='*60}")
        print("Phase: Code Cleaning (removing obfuscation / dead code)")
        print(f"{'='*60}")
        if os.path.exists(cleaned_dir):
            shutil.rmtree(cleaned_dir)
        clean_java_files(split_dir, cleaned_dir, max_workers=2)

    # ── Step 3: Code summarization via LLM ──────────
    # In resume mode, summarization skips files that already have output
    print(f"\n{'='*60}")
    print("Phase: Code Summarization")
    print(f"{'='*60}")
    os.makedirs(summarized_dir, exist_ok=True)
    summarize_java_files(cleaned_dir, summarized_dir)

    # ── Step 4: Store in Qdrant ──────────
    print(f"\n{'='*60}")
    print(f"Phase: Storing to Qdrant collection '{index_name}'")
    print(f"{'='*60}")
    process_java_summaries(
        java_directory=cleaned_dir,
        summary_directory=summarized_dir,
        weaviate_url=config["qdrant"]["url"],
        weaviate_api_key=config["qdrant"]["api_key"],
        index_name=index_name,
        openai_api_key=config["openai"]["api_key"]
    )

    # ── Step 5: Conversation analysis pipeline ──────────
    print(f"\n{'='*60}")
    print("Phase: Question-based Retrieval & Analysis")
    print(f"{'='*60}")
    run_conversation_pipeline(config)

    print(f"\n{'='*60}")
    print(f"[Done] Pipeline complete. Results in: {config['conversation_directories']['LLM_output']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
