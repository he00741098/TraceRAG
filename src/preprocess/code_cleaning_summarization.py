import openai
import os
import json
import re
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.config import load_config, set_env_variables

config = load_config()

# cleaning + summarizing can run on a smaller model if one is configured
FAST_BASE_URL = config["llm"].get("base_url_fast") or config["llm"]["base_url"]


# too simple for the LLM
_TRIVIAL_PATTERNS = [
    r"^\s*$",
    r"^\s*return\s+null\s*;\s*$",
    r"^\s*return\s+0\s*;\s*$",
    r'^\s*return\s+""\s*;\s*$',
    r"^\s*return\s+this\.\w+\s*;\s*$",
    r"^\s*this\.\w+\s*=\s*\w+\s*;\s*$",
    r"^\s*return\s+super\.\w+\(.*\)\s*;\s*$",
    r"^\s*super\.\w+\(.*\)\s*;\s*$",
]
_CANNED_SUMMARY = "Standard Java utility/boilerplate method; no suspicious behavior identified."


def _is_trivial(code: str) -> bool:
    """True if the method body is a getter/setter or nothing at all."""
    start = code.find("{")
    if start == -1:
        return True
    body = code[start + 1:]
    end = body.rfind("}")
    if end != -1:
        body = body[:end]
    body = re.sub(r"//.*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = body.strip()
    if not body:
        return True
    for pattern in _TRIVIAL_PATTERNS:
        if re.match(pattern, body):
            return True
    return False


def java_code_cleaning(java_code: str) -> str:
    """Clean up decompiled code with the LLM."""
    if _is_trivial(java_code):
        return java_code

    try:
        with open("src/Prompt_and_Question/prompts.json", "r", encoding="utf-8") as f:
            prompts = json.load(f)
    except Exception as e:
        print(f"Failed to read prompts.json: {str(e)}")
        return ""

    if "java_code_cleaning" not in prompts:
        print("prompts.json can not found  'java_code_cleaning' ")
        return ""

    prompt = prompts["java_code_cleaning"] + "This is the Java code : \n\n" + java_code

    try:
        client = openai.OpenAI(
            base_url=FAST_BASE_URL,
            api_key=config["openai"]["api_key"],
        )

        response = client.chat.completions.create(
            temperature=0,
            model=config["llm"]["cleaning_model"],
            messages=[
                {
                    "role": "system",
                    "content": "You are a code optimization assistant. Respond ONLY with the optimized code.",
                },
                {"role": "user", "content": prompt},
            ],
        )

        cleaned_code = response.choices[0].message.content.strip("\n")

        # strip markdown fences
        if cleaned_code.startswith("```"):
            cleaned_code = cleaned_code.split("\n", 1)[1] if "\n" in cleaned_code else cleaned_code[3:]
        if cleaned_code.endswith("```"):
            cleaned_code = cleaned_code[:-3].rstrip("\n")

        if cleaned_code.startswith("java\n"):
            cleaned_code = cleaned_code[5:]

        return cleaned_code

    except Exception as e:
        print(f"Error: {str(e)}")
        return ""


def process_single_file(java_file_path, input_dir, output_dir):
    try:
        with open(java_file_path, "r", encoding="utf-8") as f:
            java_code = f.read()

        optimized_code = java_code_cleaning(java_code)

        if optimized_code:
            relative_path = os.path.relpath(java_file_path, input_dir)
            output_file_path = os.path.join(output_dir, relative_path)

            output_dir_path = os.path.dirname(output_file_path)
            if not os.path.exists(output_dir_path):
                os.makedirs(output_dir_path)

            with open(output_file_path, "w", encoding="utf-8") as output_file:
                output_file.write(optimized_code)

    except Exception as e:
        print(f"Processing {java_file_path} error: {str(e)}")


def clean_java_files(input_dir: str, output_dir: str, max_workers: int = 2):
    """Clean all .java files under input_dir, in parallel."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    java_files = []
    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith(".java"):
                java_files.append(os.path.join(root, file))

    print(f" {len(java_files)}  Java files found , parallelly processing...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_single_file, java_file, input_dir, output_dir)
            for java_file in java_files
        ]

        for _ in tqdm(as_completed(futures), total=len(futures), desc="clean Java code"):
            pass


def generate_code_summary(java_code: str) -> str:
    """Summarize a code snippet, highlighting suspicious behavior."""
    try:
        with open("src/Prompt_and_Question/prompts.json", "r", encoding="utf-8") as f:
            prompts = json.load(f)
    except Exception as e:
        print(f"Failed to read prompts.json : {str(e)}")
        return ""

    if "generate_code_summary" not in prompts:
        print("prompts.json can not found 'generate_code_summary' ")
        return ""

    prompt = prompts["generate_code_summary"] + "This is the Java code : \n\n" + java_code

    client = openai.OpenAI(
        base_url=FAST_BASE_URL,
        api_key=config["openai"]["api_key"],
    )
    try:
        response = client.chat.completions.create(
            temperature=0,
            model=config["llm"]["summary_model"],
            messages=[
                {
                    "role": "system",
                    "content": "You are a code analysis assistant. Respond ONLY with a detailed summary as instructed.",
                },
                {"role": "user", "content": prompt},
            ],
        )

        cleaned_code = response.choices[0].message.content.strip("`\n")

        return cleaned_code

    except Exception as e:
        return f"An error occurred: {str(e)}"


def process_single_file_1(java_file_path, input_dir, output_dir):
    try:
        with open(java_file_path, "r", encoding="utf-8") as f:
            java_code = f.read()

        if _is_trivial(java_code):
            summary = _CANNED_SUMMARY
        else:
            summary = generate_code_summary(java_code)

        relative_path = os.path.relpath(java_file_path, input_dir)

        output_file_path = os.path.join(
            output_dir, os.path.splitext(relative_path)[0] + ".txt"
        )

        output_dir_path = os.path.dirname(output_file_path)
        if not os.path.exists(output_dir_path):
            os.makedirs(output_dir_path)

        with open(output_file_path, "w", encoding="utf-8") as summary_file:
            summary_file.write(summary)

    except Exception as e:
        print(f"Error processing {java_file_path}: {str(e)}")


def summarize_java_files(input_dir: str, output_dir: str):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    java_files = []
    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith(".java"):
                java_files.append(os.path.join(root, file))

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(process_single_file_1, java_file, input_dir, output_dir)
            for java_file in java_files
        ]

        for _ in tqdm(
            as_completed(futures), total=len(futures), desc="Processing Java Files"
        ):
            pass
