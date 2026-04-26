import argparse
import csv
import io
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from docx import Document
from flask import Flask, jsonify, render_template, request, send_file
from pypdf import PdfReader
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "storage" / "uploads"
RESULT_DIR = BASE_DIR / "storage" / "results"
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


@dataclass
class MemoItem:
    key: str
    prompt: str
    answer: str
    points: float


def normalize(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def read_upload(file_storage) -> str:
    suffix = Path(file_storage.filename).suffix.lower()
    data = file_storage.read()
    file_storage.stream.seek(0)
    if suffix in {".txt", ".md"}:
        return data.decode("utf-8", errors="ignore")
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        document = Document(io.BytesIO(data))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    raise ValueError(f"Unsupported file type: {suffix}")


def extract_points(text: str) -> tuple[str, float]:
    patterns = [
        r"\[(\d+(?:\.\d+)?)\s*(?:marks?|pts?|points?)?\]",
        r"\((\d+(?:\.\d+)?)\s*(?:marks?|pts?|points?)\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            cleaned = (text[: match.start()] + text[match.end() :]).strip()
            return cleaned, float(match.group(1))
    return text.strip(), 1.0


def split_keyed_lines(text: str) -> list[tuple[str, str]]:
    keyed = []
    pattern = re.compile(
        r"^\s*(?:question\s*)?([0-9]+[a-z]?|[a-z])[\).\:-]\s*(.+)$",
        flags=re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            keyed.append((match.group(1).lower(), match.group(2).strip()))
    return keyed


def parse_memo(text: str) -> list[MemoItem]:
    keyed = split_keyed_lines(text)
    if not keyed:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        keyed = [(str(index + 1), paragraph) for index, paragraph in enumerate(paragraphs)]

    items = []
    for key, body in keyed:
        body, points = extract_points(body)
        if "::" in body:
            prompt, answer = body.split("::", 1)
        elif "=>" in body:
            prompt, answer = body.split("=>", 1)
        elif " - " in body:
            prompt, answer = body.split(" - ", 1)
        else:
            prompt, answer = "", body
        items.append(MemoItem(key=key, prompt=prompt.strip(), answer=answer.strip(), points=points))
    return items


def parse_answers(text: str) -> dict[str, str]:
    keyed = split_keyed_lines(text)
    if keyed:
        return {key: answer for key, answer in keyed}
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return {str(index + 1): paragraph for index, paragraph in enumerate(paragraphs)}


def accepted_answers(answer: str) -> Iterable[str]:
    pieces = re.split(r"\s+(?:or|OR)\s+|;|\s*/\s*", answer)
    cleaned = [piece.strip() for piece in pieces if piece.strip()]
    return cleaned or [answer]


def grade_answer(expected: str, actual: str, threshold: float) -> tuple[float, str, float]:
    expected_norms = [normalize(answer) for answer in accepted_answers(expected)]
    actual_norm = normalize(actual)
    if not actual_norm:
        return 0.0, "No answer found.", 0.0

    best_ratio = 0.0
    for expected_norm in expected_norms:
        if not expected_norm:
            continue
        if expected_norm in actual_norm:
            best_ratio = 1.0
            break
        sequence_ratio = SequenceMatcher(None, expected_norm, actual_norm).ratio()
        expected_tokens = set(expected_norm.split())
        actual_tokens = set(actual_norm.split())
        token_ratio = len(expected_tokens & actual_tokens) / len(expected_tokens) if expected_tokens else 0.0
        ratio = max(sequence_ratio, token_ratio)
        best_ratio = max(best_ratio, ratio)

    if best_ratio >= threshold:
        return 1.0, "Matches the memo.", best_ratio
    if best_ratio >= max(0.45, threshold - 0.25):
        return 0.5, "Partially matches the memo; review recommended.", best_ratio
    return 0.0, "Does not sufficiently match the memo.", best_ratio


def mark_submission(filename: str, text: str, memo_items: list[MemoItem], threshold: float) -> dict:
    answers = parse_answers(text)
    rows = []
    total = 0.0
    possible = 0.0

    for item in memo_items:
        actual = answers.get(item.key, "")
        fraction, comment, confidence = grade_answer(item.answer, actual, threshold)
        score = round(item.points * fraction, 2)
        possible += item.points
        total += score
        rows.append(
            {
                "question": item.key,
                "prompt": item.prompt,
                "expected": item.answer,
                "student_answer": actual,
                "score": score,
                "points": item.points,
                "confidence": round(confidence, 3),
                "comment": comment,
            }
        )

    percent = round((total / possible) * 100, 1) if possible else 0.0
    return {
        "filename": filename,
        "score": round(total, 2),
        "possible": round(possible, 2),
        "percent": percent,
        "questions": rows,
    }


def save_files(files) -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for file_storage in files:
        if file_storage and file_storage.filename:
            name = secure_filename(file_storage.filename)
            file_storage.save(UPLOAD_DIR / name)


def build_csv(results: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["file", "question", "score", "points", "confidence", "comment", "student_answer", "expected"])
    for result in results:
        for row in result["questions"]:
            writer.writerow(
                [
                    result["filename"],
                    row["question"],
                    row["score"],
                    row["points"],
                    row["confidence"],
                    row["comment"],
                    row["student_answer"],
                    row["expected"],
                ]
            )
    return buffer.getvalue()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/mark")
def api_mark():
    memo = request.files.get("memo")
    tests = request.files.getlist("tests")
    threshold = float(request.form.get("threshold", "0.72"))

    if not memo or not memo.filename:
        return jsonify({"error": "Upload a memo file."}), 400
    if not tests:
        return jsonify({"error": "Upload at least one test file."}), 400
    if not allowed_file(memo.filename) or any(not allowed_file(test.filename) for test in tests):
        return jsonify({"error": "Use txt, md, pdf, or docx files only."}), 400

    memo_text = read_upload(memo)
    memo_items = parse_memo(memo_text)
    if not memo_items:
        return jsonify({"error": "The memo did not contain markable answers."}), 400

    results = []
    for test in tests:
        text = read_upload(test)
        results.append(mark_submission(test.filename, text, memo_items, threshold))

    save_files([memo, *tests])
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    (RESULT_DIR / "latest.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (RESULT_DIR / "latest.csv").write_text(build_csv(results), encoding="utf-8")

    return jsonify({"memo_items": len(memo_items), "results": results})


@app.get("/api/results/latest.csv")
def latest_csv():
    path = RESULT_DIR / "latest.csv"
    if not path.exists():
        return jsonify({"error": "No results have been generated yet."}), 404
    return send_file(path, as_attachment=True, download_name="marking-results.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="7860")
    args = parser.parse_args()
    print(f"Marking App running at http://{args.host}:{args.port}", flush=True)
    app.run(host=args.host, port=int(args.port))
