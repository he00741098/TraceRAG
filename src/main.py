import sys
import os
import shutil
import json
import argparse
import yaml
from src.config import load_config, set_env_variables

from src.preprocess.pipeline import preprocess_pipeline

from src.conversation.first_phase import execute_query
from src.conversation.first_phase_result_precess import split_and_store_java_code
from src.conversation.second_phase import model_conversation

from src.postprocess.combine_single_question_report import quesiton_report_generation
from src.postprocess.txt2markwon_and_html import convert_txt_to_md_and_html
from src.postprocess.Final_report_Generation import apk_report_generation


CONFIG_PATH = "config.yaml"

def update_config_index_name(new_index_name, config_path=CONFIG_PATH):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    config['qdrant']['collection_name'] = new_index_name

    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True)


def _clean_output_dir(output_dir):
    """Remove previous run's output to prevent cross-contamination."""
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)


def _scope_config_to_output(config, output_dir):
    """Rewrite all config paths to be scoped under output_dir."""
    config["directories"]["java_dir"] = f"{output_dir}/reversedAPK/sources"
    config["directories"]["apk_info_dir"] = f"{output_dir}/APK_info.txt"
    config["directories"]["reversed_apk_dir"] = f"{output_dir}/reversedAPK"
    config["conversation_directories"]["LLM_output"] = f"{output_dir}/LLM_output"
    config["conversation_directories"]["user_query_analyze_path"] = f"{output_dir}/LLM_output/analyze"
    config["conversation_directories"]["user_query_retrieval_filtered_path"] = f"{output_dir}/LLM_output/retrieve/user_query_retrieve_filtered_result"
    config["conversation_directories"]["user_query_retrieval_filtered_split_path"] = f"{output_dir}/LLM_output/retrieve/split_filtered_result"
    config["conversation_directories"]["user_query_retrieval_save_path"] = f"{output_dir}/LLM_output/retrieve/user_query_retrieve_result"


if __name__ == "__main__":

    set_env_variables()

    config = load_config()

    parser = argparse.ArgumentParser(description="Run APK analysis pipeline.")
    parser.add_argument("apk_directory", type=str, help="Path to the APK file or directory containing APKs.")
    parser.add_argument("index_name", type=str, help="Index name for the vector database.")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Base output directory (default: output/<index_name>). "
                             "Output is scoped per-APK so runs never collide.")

    args = parser.parse_args()
    apk_directory = args.apk_directory
    index_name = args.index_name
    output_dir = args.output_dir or f"output/{index_name}"

    # Update YAML file with new collection name
    update_config_index_name(index_name)

    # Reload config to pick up the index_name change
    config = load_config()

    # Scope all output to the per-APK directory
    _scope_config_to_output(config, output_dir)

    # Clean previous run's output to prevent cross-contamination
    _clean_output_dir(output_dir)

    # ── Preprocessing pipeline ──────────────────────────────────────────
    # 1. Decompile APK to Java
    # 2. Split into methods
    # 3. Clean code with LLM
    # 4. Generate summaries with LLM
    # 5. Store in Qdrant vector database
    preprocess_pipeline(apk_directory, index_name, config_dict=config)

    # ── Load 5-category question set ────────────────────────────────────
    try:
        with open("src/Prompt_and_Question/questions.json", "r", encoding="utf-8") as f:
            questions = json.load(f)
    except Exception as e:
        print(f"Failed to read questions.json: {str(e)}")
        sys.exit(1)

    # ── Phase 1 + Phase 2: iterate over all 22 questions ────────────────
    for category_name, category_info in questions.items():
        for idx, retrieve_question in enumerate(category_info["questions"]):
            question_name = f"{category_name}_{idx + 1}"
            print(f"\n{'='*50}")
            print(f"Processing: {question_name}")
            print(f"  Query: {retrieve_question}")
            print(f"{'='*50}")

            try:
                # Phase 1: retrieve relevant code from Qdrant
                execute_query(retrieve_question, config_dict=config)
                split_and_store_java_code(config_dict=config)

                output_dir_analyze = config["conversation_directories"]["user_query_analyze_path"]
                os.makedirs(output_dir_analyze, exist_ok=True)

                code_snippet_path = config["conversation_directories"]["user_query_retrieval_filtered_split_path"]
                if not os.path.exists(code_snippet_path):
                    print(f"[Error] The directory '{code_snippet_path}' does not exist.")
                    continue

                print(f"[Info] Processing .txt files in: {code_snippet_path}")

                # Read all code snippets into a list first
                snippet_files = sorted(
                    [f for f in os.listdir(code_snippet_path) if f.endswith(".txt")]
                )
                if not snippet_files:
                    print(f"[Skip] No snippet files found for {question_name}")
                    continue

                snippets = []
                for filename in snippet_files:
                    file_path = os.path.join(code_snippet_path, filename)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            snippets.append(f.read())
                    except Exception as e:
                        print(f"[Warning] Failed to read {filename}: {e}")

                print(f"[Info] {len(snippets)} snippets loaded. Running batched Phase 2...")

                # ── Batched Phase 2 with parallel execution ────────────
                # Each batch combines batch_size snippets into one LLM call.
                # Batches run in parallel via ThreadPoolExecutor.
                from concurrent.futures import ThreadPoolExecutor, as_completed

                BATCH_SIZE = 5
                MAX_PARALLEL = 3
                file_contents = []
                total_chunks = (len(snippets) + BATCH_SIZE - 1) // BATCH_SIZE

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
                        f"{retrieve_question}. Please analyze them together to "
                        f"identify any potential malicious behavior."
                    )
                    chunk_num = chunk_idx + 1
                    print(f"  [Phase 2] Batch {chunk_num}/{total_chunks} (started)")
                    result = model_conversation(analyze_question, combined, config_dict=config)
                    chunk_output = os.path.join(
                        output_dir_analyze, f'batched_analysis_result_chunk_{chunk_num}.txt'
                    )
                    with open(chunk_output, 'w', encoding='utf-8') as out_f:
                        out_f.write(str(result))
                    print(f"  [Phase 2] Batch {chunk_num}/{total_chunks} (done)")
                    return (chunk_num, f"Batched conversation history (Chunk {chunk_num})\n{str(result)}")

                chunk_results = {}
                with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as executor:
                    futures = {}
                    for i in range(0, len(snippets), BATCH_SIZE):
                        batch = snippets[i:i + BATCH_SIZE]
                        chunk_idx = i // BATCH_SIZE
                        futures[executor.submit(process_batch, chunk_idx, i, batch)] = chunk_idx
                    for future in as_completed(futures):
                        chunk_num, text = future.result()
                        chunk_results[chunk_num] = text

                # Assemble in order
                for chunk_num in sorted(chunk_results.keys()):
                    file_contents.append(chunk_results[chunk_num])
                print(f"  [Done] {total_chunks} batches processed for {question_name}.")

                # Write combined analysis for this question
                combined_file_path = os.path.join(output_dir_analyze, f'{question_name}_combined.txt')
                with open(combined_file_path, 'w', encoding='utf-8') as combined_f:
                    combined_f.write("\n\n".join(file_contents))

                print(f"[Done] Files processed for {question_name}, combined report saved.")

                # Generate per-question report
                try:
                    final_result = quesiton_report_generation(file_contents, config_dict=config)
                    final_report_path = os.path.join(output_dir_analyze, f'{question_name}_report.txt')
                    with open(final_report_path, 'w', encoding='utf-8') as f:
                        f.write(final_result)

                    print(f"[Final Report Saved] {final_report_path}")
                    convert_txt_to_md_and_html(final_report_path)

                except Exception as e:
                    print(f"[Error] Failed to run quesiton_report_generation. Error: {e}")

                # ── Organize output into per-question directories ────────
                # This prevents sub-questions from overwriting each other.
                try:
                    llm_output_base = config["conversation_directories"]["LLM_output"]

                    # Derive category and question number from name
                    # e.g. "Information_Theft_3" → category="Information_Theft", id="3"
                    category = question_name.rsplit("_", 1)[0]
                    question_id = question_name.rsplit("_", 1)[-1]

                    category_dir = os.path.join(llm_output_base, category)
                    question_output_dir = os.path.join(category_dir, f"Question_{question_id}")
                    os.makedirs(question_output_dir, exist_ok=True)

                    folders_to_move = ['analyze', 'retrieve']
                    for folder_name in folders_to_move:
                        src_folder = os.path.join(llm_output_base, folder_name)
                        dst_folder = os.path.join(question_output_dir, folder_name)

                        if os.path.exists(src_folder):
                            if os.path.exists(dst_folder):
                                shutil.rmtree(dst_folder)
                            shutil.move(src_folder, dst_folder)
                            print(f"[Moved] {folder_name} → {question_output_dir}")
                        else:
                            print(f"[Skipped] {folder_name} not found in {llm_output_base}")

                except Exception as e:
                    print(f"[Error] Failed to move folders for {question_name}: {e}")

            except Exception as e:
                print(f"Error processing {question_name}: {str(e)}")

    # ── Aggregate all question reports into final APK report ────────────
    def collect_question_reports(base_dir):
        """Collect all per-question reports from the nested directory structure."""
        final_report = ""
        for category in sorted(os.listdir(base_dir)):
            category_path = os.path.join(base_dir, category)
            if not os.path.isdir(category_path):
                continue
            for question_dir in sorted(os.listdir(category_path)):
                question_path = os.path.join(category_path, question_dir)
                analyze_dir = os.path.join(question_path, "analyze")
                if not os.path.isdir(analyze_dir):
                    continue
                # Find the *_report.txt file for this question
                for fname in sorted(os.listdir(analyze_dir)):
                    if fname.endswith("_report.txt"):
                        report_path = os.path.join(analyze_dir, fname)
                        with open(report_path, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                        qname = fname.replace("_report.txt", "")
                        final_report += f"{category}/{qname} Report:\n{content}\n\n"
                        break
        return final_report.strip()

    llm_output_base = config["conversation_directories"]["LLM_output"]
    merged_question_reports = collect_question_reports(llm_output_base)

    if merged_question_reports:
        apk_analyze_result = apk_report_generation(merged_question_reports, config_dict=config)
        output_path = os.path.join(llm_output_base, "APK_Report.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(apk_analyze_result)
        convert_txt_to_md_and_html(output_path)
        print(f"\n[Final APK Report] {output_path}")
    else:
        print("\n[Final APK Report] No question reports found to aggregate.")
