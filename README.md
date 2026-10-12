# 🔍 GNOME Embedding Search

Multimodal **semantic file search** for GNOME Shell, powered by Google's
[EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) model and
[FAISS](https://github.com/facebookresearch/faiss).

Instead of matching file names, this project turns your documents, images,
videos and audio into vectors in a single shared space. You can type
natural-language queries such as _"zebra in a video"_, _"a photo of a red car"_
or _"notes about quantum computing"_ and get the matching file — including the
exact timestamp inside a video — straight from the GNOME activities search.

## ✨ Features

- **Semantic, cross-modal search** — one query language for text, images, video
  and audio. Text queries can match image/video content and vice-versa.
- **Rich previews in the GNOME overview** — large thumbnail, file path,
  relevance score and, for videos, the matching timestamp.
- **Jump to the right moment** — clicking a video result opens it in your
  **default media player** at the found timestamp (when the player supports
  seeking).
- **Multilingual** — EmbeddingGemma 2 understands 100+ languages, so you can
  search in your own language.
- **Real-time index** — a file watcher keeps the index up to date as files are
  created, changed or deleted.
- **Local & private** — everything runs on your machine through a `systemd
  --user` service and a D-Bus interface. No data leaves your computer.

## 🏗️ How it works

```
┌──────────────────────────────┐
│ GNOME Shell (activities)     │  search bar → EmbeddingSearchProvider
│  Extension (GJS / ESM)       │
└───────────────┬──────────────┘
                │ D-Bus (org.gnome.EmbeddingSearch)
┌───────────────▼──────────────┐
│ Python backend               │  ┌───────────────┐
│  EmbeddingGemma 2 (torch)    │─▶│ FAISS index   │
│  SQLite metadata             │  └───────────────┘
│  inotify file watcher        │  ┌───────────────┐
└──────────────────────────────┘─▶│ thumbnails    │
                                   └───────────────┘
```

- The backend encodes the query, searches a FAISS `IndexFlatIP` (cosine
  similarity on L2-normalised vectors) and returns JSON results over D-Bus.
- Embeddings are truncated using **Matryoshka Representation Learning** (default
  `256` dims) to keep the index small with negligible quality loss.

## 📦 Project layout

```
GnomeSearch_Embedding/
├── backend/        Python D-Bus service (model, indexer, searcher, watcher)
├── extension/      GNOME Shell extension (search provider, preview widget)
├── systemd/        systemd --user unit template
├── setup.sh        One-shot installer
├── .env.example    Configuration template
└── data/           Runtime data: FAISS index, SQLite DB, thumbnails (git-ignored)
```

## ✅ Requirements

- **GNOME Shell 45+** (developed against GNOME 50)
- **Python 3.10+** with `venv`
- A CUDA-capable GPU is recommended but **not required** — set
  `CUDA_DEVICE_INDEX=-1` to run on CPU (slower).
- `ffmpeg`/`ffprobe` (optional) for audio duration probing.

## 🚀 Installation

### Automatic

```bash
git clone https://github.com/swanlepeltier/GnomeSearch_Embedding.git
cd GnomeSearch_Embedding
./setup.sh
```

`setup.sh` creates a virtual environment, installs the Python dependencies,
creates `.env`, installs and starts the `systemd --user` service, and installs
the GNOME Shell extension.

> On Wayland, GNOME Shell only loads a **newly installed** extension after you
> log out and log back in. Reloading an already-installed extension can be done
> on X11 with `Alt+F2`, then `r`, then Enter.

### Manual

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env      # then edit it
```

Start the backend:

```bash
.venv/bin/python backend/service.py
```

Install the extension (a symlink works too, which is handy for development):

```bash
mkdir -p ~/.local/share/gnome-shell/extensions
ln -s "$PWD/extension" \
  ~/.local/share/gnome-shell/extensions/embedding-search@gnome-search-embedding
gnome-extensions enable embedding-search@gnome-search-embedding
```

## ⚙️ Configuration

All settings live in `.env` (copy of `.env.example`). Paths support `~`/`$HOME`.
The most useful options:

| Variable                 | Description                                                    | Default               |
| ------------------------ | -------------------------------------------------------------- | --------------------- |
| `CUDA_DEVICE_INDEX`      | GPU index to use; `-1` forces CPU                              | `0`                   |
| `TORCH_DTYPE`            | `float32` (safe) or `bfloat16` (Ampere+ GPUs)                  | `float32`             |
| `EMBEDDING_DIM`          | Matryoshka truncation: `768`, `512`, `256`, `128`              | `256`                 |
| `MODALITY`               | Which modalities to index (`text_only`, `text_vision`, …)      | `multimodal`          |
| `WATCH_DIRS`             | Comma-separated directories to index                           | `~/Documents,…`       |
| `DATA_DIR`               | Where the index/DB/thumbnails live                             | `./data`              |
| `VIDEO_FRAME_INTERVAL`   | Seconds between sampled video frames                           | `3`                   |
| `MAX_RESULTS`            | Maximum results returned per query                             | `8`                   |
| `MIN_SCORE`              | Minimum cosine similarity to include a result                  | `0.15`                |
| `LOG_LEVEL`              | `DEBUG`, `INFO`, `WARNING`, `ERROR`                            | `INFO`                |

> **Do not use `float16`** — it produces `NaN` embeddings with this model.

## 🎯 Usage

1. Press `Super` and start typing, e.g. _zebra in a video_.
2. Results appear under **Semantic Embedding Search** with a large preview.
3. Press `Enter` (or click) to open the file. Video results open at the
   detected timestamp.

The last section of the results list shows a "launch search" entry only if the
provider implements it (this one does not, since the backend is a service).

## 🔧 Operations

```bash
# follow the backend log (model loading, indexing progress)
journalctl --user -u gnome-embedding-search -f

# restart / inspect the service
systemctl --user restart gnome-embedding-search
systemctl --user status  gnome-embedding-search
```

You can force a reindex over D-Bus at any time; the fastest way is a tiny
`gdbus` call:

```bash
# incremental reindex
gdbus call --session --dest org.gnome.EmbeddingSearch \
  --object-path /org/gnome/EmbeddingSearch \
  --method org.gnome.EmbeddingSearch.Reindex false

# full rebuild (drops the index and re-embeds everything)
gdbus call --session --dest org.gnome.EmbeddingSearch \
  --object-path /org/gnome/EmbeddingSearch \
  --method org.gnome.EmbeddingSearch.Reindex true

# service status (JSON)
gdbus call --session --dest org.gnome.EmbeddingSearch \
  --object-path /org/gnome/EmbeddingSearch \
  --method org.gnome.EmbeddingSearch.GetStatus
```

## 🐛 Troubleshooting

- **No results / "search unavailable"** — make sure the backend is running
  (`systemctl --user status gnome-embedding-search`) and that the model finished
  its first download.
- **Extension not listed** — log out and back in (required on Wayland), then
  `gnome-extensions enable embedding-search@gnome-search-embedding`.
- **Out of VRAM** — lower `EMBEDDING_DIM`, set `MODALITY=text_only`, or use a
  smaller `BATCH_SIZE`.
- **Video timestamp ignored** — the timestamp is only passed when your default
  player supports a seek flag (mpv, vlc, celluloid, smplayer, totem). Otherwise
  the file simply opens in your default player.

## 📄 License

Released under the [MIT License](LICENSE). EmbeddingGemma 2 itself is provided
by Google under the Apache 2.0 license — see its model card for details.
