# Setup Notes

Everything below is what I needed to run TraceRAG with local models on the
WM HPC cluster (SciClone). Works with llama.cpp, koboldcpp, or any server
that speaks the OpenAI API on the right ports.

## Layout

- LLM server: port 5001 (OpenAI-compatible)
- Embedding server: port 5002 (OpenAI-compatible)
- Qdrant: port 6333

All of these are pointed at localhost in config.yaml. If you want to hit
them from a laptop, tunnel the ports through the login node:

    ssh -J jhe15@bastion.wm.edu -L 5001:localhost:5001 -L 5002:localhost:5002 -L 6333:localhost:6333 jhe15@astral.sciclone.wm.edu

## Logging in

The cluster moved to astral (login node). Bastion still needs Duo:

    ssh -J jhe15@bastion.wm.edu jhe15@astral.sciclone.wm.edu

GPU nodes are as00/as01 (4x NVIDIA A30 24GB each, 8 total), batch
partition, 3 day max. Interactive node — ask for plenty of RAM or the
OOM killer will take out the servers:

    salloc -N1 -n32 --mem=128G -t 1-0:0:0 --gpus=2

Then `module load cuda/12.3` before starting anything CUDA.

## Model servers

Everything lives in ~/scr10/ai. Start scripts are ai/aistart.sh:

    cd ~/scr10/ai
    tmux new -d -s gemma './llamacpp/llama.cpp/build/bin/llama-server -m models/gemma-4-26B-A4B-it-Q8_0.gguf -ngl 99 -c 128000 --host 0.0.0.0 --port 5001 -np 2 -fa on -ctk q8_0 -ctv q8_0'
    tmux new -d -s jina './koboldcpp-linux-x64 --embeddingsmodel models/jina-embeddings-v5-omni-small-retrieval-F16.gguf --usecublas --gpulayers 99 --contextsize 8192 --port 5002 --multiuser'

The gemma line uses -np 2 (two parallel slots) plus flash attention and
quantized KV cache: with 3 slots the per-slot context drops to ~42K
tokens and long phase-2 prompts overflow. 2 slots gives ~65K each.

Models: gemma-4-26B-A4B-it-Q8_0.gguf (~25GB) and
jina-embeddings-v5-omni-small-retrieval-F16.gguf, both in ai/models/.

### Optional small model for cleaning/summarizing

Cleaning and summarizing are the high-volume steps (one LLM call per
method) and don't need the big model. Point `llm.base_url_fast` in
config.yaml at a small model on another port, e.g.:

    tmux new -d -s small './llamacpp/llama.cpp/build/bin/llama-server -m models/qwen2.5-coder-3b-instruct-q8_0.gguf -ngl 99 -c 8192 --host 0.0.0.0 --port 5003'

and set `base_url_fast: http://localhost:5003/v1` plus matching
`cleaning_model` / `summary_model` names. Leave `base_url_fast` empty to
fall back to the main model.

qwen2.5-coder-3b (Q8, ~3.6GB) is the one tested: cleaning takes ~1-9s
per method vs 1-7 minutes on the big model, and the output quality held
up fine for clean/summarize.

Qdrant: ~/scr10/vectorDB, `bash qdrantStart.sh` (tmux session "qdrant").

### llama.cpp must be rebuilt for A30 (sm_80)

The prebuilt binary targets the old gulf nodes and crashes on the A30s
with "no kernel image is available for execution on the device". Rebuild
with the right CUDA arch:

    cd ~/scr10/ai/llamacpp/llama.cpp
    rm -rf build
    cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=80
    cmake --build build -j 8 --target llama-server

Takes ~10-15 min. koboldcpp works without a rebuild (it uses cuBLAS).

## Python environment

Cluster Python is 3.9. Deps go in ~/.local (no sudo):

    pip install --user -r requirements.txt

## Running

Single APK through the main pipeline:

    python3 -m src.main path/to/app.apk <collection-name>

Pre-split source (the JSONL files the original project shipped):

    python3 -m src.jsonl_pipeline path/to/source.jsonl <collection-name> --output-dir output/<sha256>

Both support `--skip-preprocess` to re-run only the retrieval/analysis
phase against an existing Qdrant collection (handy after a crash), and
the JSONL pipeline has `--resume` to skip already-ingested files.

The JSONL pipeline understands both the original {"rel_path", "code"}
format and OpenAI batch-API dumps ({"custom_id", "body": ...}).

## Gotchas

- Delete the Qdrant collection (or use a fresh name) when re-running the
  same APK, or you'll get duplicate points.
- config.yaml gets rewritten on every run (collection name), so don't
  keep edits in it between runs.
- 2x A30 (48GB) fits gemma-4-26B Q8_0 with all layers on GPU.
- gemma-4 is a thinking model: it fills reasoning_content first, then
  content. Give it enough max_tokens.
- The local LLM loops more than GPT did in phase 2. There's a hard cap
  of 16 retrieval rounds per batch in second_phase.py so it can't hang.
- Long runs go in tmux so they survive disconnects:
  `tmux new -d -s name 'command | tee log.txt'`
