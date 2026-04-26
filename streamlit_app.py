import csv
import hmac
import io
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import streamlit as st
from docx import Document
from pypdf import PdfReader


ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


@dataclass
class MemoItem:
    key: str
    prompt: str
    answer: str
    points: float


def configured_access_code() -> str:
    try:
        return str(st.secrets.get("MARKING_APP_PASSCODE", "")).strip()
    except Exception:
        return os.environ.get("MARKING_APP_PASSCODE", "").strip()


def normalize(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def read_upload(uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    data = uploaded_file.getvalue()
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


def require_access() -> bool:
    access_code = configured_access_code()
    if not access_code:
        return True
    supplied = st.text_input("Access code", type="password")
    if not supplied:
        return False
    if hmac.compare_digest(supplied, access_code):
        return True
    st.error("That access code is not correct.")
    return False


st.set_page_config(page_title="Marking App", page_icon="✓", layout="wide")
st.title("Marking App")
st.caption("Upload one memo and one or more learner scripts, then review scores question by question.")

if not require_access():
    st.stop()

left, right = st.columns([0.9, 1.4])

with left:
    memo_file = st.file_uploader("Memo", type=["txt", "md", "pdf", "docx"])
    test_files = st.file_uploader("Tests", type=["txt", "md", "pdf", "docx"], accept_multiple_files=True)
    threshold = st.slider("Strictness", min_value=0.55, max_value=0.90, value=0.72, step=0.01)
    mark_clicked = st.button("Mark tests", type="primary")
    st.info("Memo lines work best like: 1. Photosynthesis is the process plants use to make food [2]")

with right:
    if mark_clicked:
        if memo_file is None:
            st.error("Upload a memo file.")
            st.stop()
        if not test_files:
            st.error("Upload at least one test file.")
            st.stop()
        if Path(memo_file.name).suffix.lower() not in ALLOWED_EXTENSIONS:
            st.error("Use txt, md, pdf, or docx files only.")
            st.stop()

        try:
            memo_text = read_upload(memo_file)
            memo_items = parse_memo(memo_text)
            if not memo_items:
                st.error("The memo did not contain markable answers.")
                st.stop()

            results = []
            for test_file in test_files:
                if Path(test_file.name).suffix.lower() not in ALLOWED_EXTENSIONS:
                    st.error(f"{test_file.name} is not a supported file type.")
                    st.stop()
                results.append(mark_submission(test_file.name, read_upload(test_file), memo_items, threshold))
        except Exception as exc:
            st.error(f"Could not mark files: {exc}")
            st.stop()

        st.success(f"Marked {len(results)} script{'s' if len(results) != 1 else ''}.")
        st.download_button(
            "Download CSV",
            data=build_csv(results),
            file_name="marking-results.csv",
            mime="text/csv",
        )

        for result in results:
            st.subheader(f"{result['filename']} - {result['score']} / {result['possible']} ({result['percent']}%)")
            for row in result["questions"]:
                with st.expander(f"Q{row['question']} - {row['score']} / {row['points']}"):
                    st.write(f"Confidence: {round(row['confidence'] * 100)}%")
                    st.write(f"Expected: {row['expected']}")
                    st.write(f"Student: {row['student_answer'] or 'No answer found'}")
                    st.write(row["comment"])
    else:
        st.write("Upload files and click **Mark tests** to begin.")
