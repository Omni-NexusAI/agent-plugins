"""Fetch a small, fixed sample of public question sets and convert it for run_bench.

    python prepare_datasets.py gsm8k --raw RAW_DIR --out data
    python prepare_datasets.py mmlu_pro --raw RAW_DIR --out data

Writes ``<name>-dev.jsonl`` and ``<name>-heldout.jsonl`` (alternate questions of
one seeded sample, so the halves never overlap). Nothing is fetched unless you
run this; the questions are not committed. Both sets are MIT licensed.

  gsm8k     grade-school maths word problems, numeric answer
            github.com/openai/grade-school-math (test.jsonl, about 0.75 MB)
  mmlu_pro  ten-choice questions across 14 subjects
            huggingface.co/datasets/TIGER-Lab/MMLU-Pro (test split, sampled in
            pages through the dataset viewer API)
"""

from __future__ import annotations

import argparse
import json
import random
import urllib.request
from pathlib import Path

GSM8K = "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl"
MMLU_PRO = ("https://datasets-server.huggingface.co/rows?dataset=TIGER-Lab%2FMMLU-Pro"
            "&config=default&split=test&offset={offset}&length={length}")
MMLU_PRO_ROWS = 12032


def fetch(url: str, target: Path) -> bytes:
    if target.exists():
        return target.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": "looped-bench"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    target.write_bytes(data)
    return data


def gsm8k(raw: Path, count: int, seed: int) -> list[dict]:
    lines = fetch(GSM8K, raw / "gsm8k-test.jsonl").decode("utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    picked = sorted(random.Random(seed).sample(range(len(rows)), count))
    tasks = []
    for index in picked:
        answer = rows[index]["answer"].rsplit("####", 1)[-1].strip().replace(",", "")
        tasks.append({"id": f"gsm8k-{index:04d}", "kind": "qa", "answer": answer,
                      "question": rows[index]["question"].strip()
                      + " Put just the final number in the answer text."})
    return tasks


def mmlu_pro(raw: Path, count: int, seed: int) -> list[dict]:
    page = 10
    pages = max(1, count // page)
    step = MMLU_PRO_ROWS // pages
    start = random.Random(seed).randrange(step - page)
    tasks = []
    for number in range(pages):             # evenly spaced pages cover every subject
        offset = start + number * step
        data = json.loads(fetch(MMLU_PRO.format(offset=offset, length=page),
                                raw / f"mmlu-pro-{offset:05d}.json").decode("utf-8"))
        for entry in data["rows"]:
            row = entry["row"]
            options = [str(option) for option in row["options"] if str(option) != "N/A"]
            tasks.append({"id": f"mmlu-pro-{row['question_id']}", "kind": "qa",
                          "question": str(row["question"]).strip(), "choices": options,
                          "answer": str(row["answer"]).strip(), "category": row.get("category", "")})
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", choices=("gsm8k", "mmlu_pro"))
    parser.add_argument("--raw", type=Path, required=True, help="empty folder for the downloads")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--count", type=int, default=240)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    args.raw.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    tasks = {"gsm8k": gsm8k, "mmlu_pro": mmlu_pro}[args.name](args.raw, args.count, args.seed)
    for offset, split in enumerate(("dev", "heldout")):
        target = args.out / f"{args.name}-{split}.jsonl"
        target.write_text("".join(json.dumps(task, ensure_ascii=False) + "\n" for task in tasks[offset::2]),
                          encoding="utf-8", newline="\n")
        print(f"{target}: {len(tasks[offset::2])} questions")


if __name__ == "__main__":
    main()
