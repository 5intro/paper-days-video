#!/usr/bin/env python3
"""Download the fixed Qwen snapshot and record its local path in a project config."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from voice_common import (MODEL_ID, MODEL_REVISION, atomic_json, load_config,
                          model_identity, resolve_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Project config.json to update.")
    locations = parser.add_mutually_exclusive_group()
    locations.add_argument("--local-dir", help="Download directory, relative to the config directory.")
    locations.add_argument("--cache-dir", help="Use a shared Hugging Face cache instead of a project copy.")
    args = parser.parse_args()
    config_path, root, config = load_config(args.config)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    from huggingface_hub import snapshot_download

    kwargs = {"repo_id": MODEL_ID, "revision": MODEL_REVISION}
    if args.cache_dir:
        kwargs["cache_dir"] = str(resolve_path(root, args.cache_dir))
    else:
        kwargs["local_dir"] = str(resolve_path(root, args.local_dir or config["model_path"]))
    print(f"Downloading {MODEL_ID} at revision {MODEL_REVISION}", flush=True)
    snapshot = Path(snapshot_download(**kwargs)).resolve()
    identity = model_identity(snapshot)
    atomic_json(snapshot / "paper-days-model-lock.json", {
        "repo_id": MODEL_ID, "revision": MODEL_REVISION, **identity,
    })
    original = json.loads(config_path.read_text(encoding="utf-8"))
    # Keep a project-contained model path relative; shared caches may live on another drive.
    try:
        stored_path = snapshot.relative_to(root).as_posix()
    except ValueError:
        stored_path = str(snapshot)
    original["model_path"] = stored_path
    atomic_json(config_path, original)
    print(json.dumps({"model_path": stored_path, "revision": MODEL_REVISION,
                      "model_files_sha256": identity["files_sha256"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
