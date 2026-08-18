# Setup Notes

Everything below is what I needed to run TraceRAG with local models on the
WM HPC cluster (SciClone). Works with any server
that speaks the OpenAI API on the right ports. Kobold Cpp has been the current choice 
since they provide a binary allowing for easy deployment.

Note: commands are based on how I used them, and should be modified.

## Layout

- LLM server: port 5001 (OpenAI-compatible)
- Embedding server: port 5002 (OpenAI-compatible)
- Qdrant: port 6333

All of these are pointed at localhost in config.yaml. A helpful way to get access to the ports is:

    ssh -J jhe15@bastion.wm.edu -L 5001:node_name:5001 -L 5002:node_name:5002 -L 6333:node_name:6333 jhe15@astral.sciclone.wm.edu

Note: see https://www.wm.edu/offices/it/services/researchcomputing/atwm/systemarchitecture/nodes/ for information on available clusters and nodes.

## Logging in

To login to the HPC from a remote location, you need to go through the bastion node, which needs Duo for verification every time. So far, I've used the astral and gulf nodes since they have GPUs:

    ssh -J jhe15@bastion.wm.edu jhe15@astral.sciclone.wm.edu

To allocate an interactive node: 

    salloc -N1 -n32 --mem=128G -t 1-0:0:0 --gpus=2
    
Note: If you don't provision enough RAM, the LLM servers may get killed

To see currently running tasks, use `squeue`. If there are no spare gpus, the salloc will just wait/hang.

You may need to run `module load cuda/12.3` if you are using cuda.

## Model servers

I put all the AI stuff in ~/scr10/ai. Note that the referenced files/directories will most likely not be accessible to you, and you will need to set this up yourself.
scr10 is basically a remote drive that can be accessed from any node. Here are the commands I used to start the models:

    cd ~/scr10/ai
    tmux new -d -s gemma './llamacpp/llama.cpp/build/bin/llama-server -m models/gemma-4-26B-A4B-it-Q8_0.gguf -ngl 99 -c 128000 --host 0.0.0.0 --port 5001 -np 2 -fa on -ctk q8_0 -ctv q8_0'
    tmux new -d -s jina './koboldcpp-linux-x64 --embeddingsmodel models/jina-embeddings-v5-omni-small-retrieval-F16.gguf --usecublas --gpulayers 99 --contextsize 8192 --port 5002 --multiuser'

Tmux is used to keep the LLM servers in the background. If you aren't familiar with it, you may want to read up on the controls.

Models: gemma-4-26B-A4B-it-Q8_0.gguf (~25GB) and
jina-embeddings-v5-omni-small-retrieval-F16.gguf, both downloaded from Hugging Face, and kept in ~/scr10/ai/models/

### Optional small model for cleaning/summarizing

Cleaning and summarizing are the high-volume steps (one LLM call per
method) and don't need the big model. Set `llm.base_url_fast` in
config.yaml to a small model on another port, for instance:

    tmux new -d -s small './llamacpp/llama.cpp/build/bin/llama-server -m models/qwen2.5-coder-3b-instruct-q8_0.gguf -ngl 99 -c 8192 --host 0.0.0.0 --port 5003'

and set `base_url_fast: http://localhost:5003/v1` plus
`cleaning_model` / `summary_model` names (If you are using Kobold Cpp, the names shouldn't matter since it will at most serve a model and an embeddings model (which uses a different endpoint) per instance). Leave `base_url_fast` empty to
just use the main model.

qwen2.5-coder-3b (Q8, ~3.6GB) was tested and cleaning took ~1-9s
per method vs 1-7 minutes on the big model. The output quality appeared to hold
up fine for cleaning and summarizing.

## Qdrant:

Instead of Weaviate, I opted to just locally host Qdrant, another vector database.
A binary for it can be sourced on Github, and just executing that binary should be enough to start it.

`tmux new -d -s qdrant './qdrant'`

You can view the Qdrant web interface by tunneling the 6333 port. For instance:

`ssh -J jhe15@bastion.wm.edu -L 6333:gu03:6333 jhe15@gulf.sciclone.wm.edu`

This should then allow you to go to localhost:6333/dashboard.

## Python environment

Cluster Python is 3.9. Deps go in ~/.local (Note: there is no sudo access):

    pip install --user -r requirements.txt

## Running

Single APK through the main pipeline:

    python3 -m src.main path/to/app.apk <collection-name>

Prior source (the JSONL files the original project shipped located in `TraceRAG result and source code.zip`):

    python3 -m src.jsonl_pipeline path/to/source.jsonl <collection-name> --output-dir output/<sha256>

Both support `--skip-preprocess` to re-run only the retrieval/analysis
phase against an existing Qdrant collection (in case of a crash), and
the JSONL pipeline has `--resume` to skip already-ingested files.

Note that a few of the JSONL files use a different format, which isn't fully supported. The pipeline prefers the {"rel_path", "code"}
format. The OpenAI batch-API dumps ({"custom_id", "body": ...}) are more complicated, so they haven't been fully addressed.

## Potential issues you may encounter

- Delete the Qdrant collection (or use a fresh name) when re-running the
  same APK, or you'll get duplicate points.
- config.yaml gets rewritten on every run (collection name), so don't
  edit it between runs.
- 2x A30 (48GB) fits gemma-4-26B Q8_0 with all layers on GPU.
- gemma-4 is a thinking model: it fills reasoning_content first, then
  content. You may need to adjust max_tokens.
- The local LLM loops a lot in phase 2. There's a hard cap
  of 16 retrieval rounds per batch in second_phase.py so it doesn't hang.
