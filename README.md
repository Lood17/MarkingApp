# Marking App

Marking App is a local teacher workflow for checking learner scripts against a memo. Upload one memo and one or more tests, then the app extracts answers, compares each question to the memo, assigns scores, and highlights answers that need review.

Supported uploads: `.txt`, `.md`, `.pdf`, and `.docx`. PDF support reads embedded text; scanned image PDFs need OCR before upload.

## How to Use

1. Run `install.js` in Pinokio.
2. Run `start.js`.
3. Open the Web UI.
4. Upload a memo and test files.
5. Review the scores and download the CSV result file.

Memo lines work best in this format:

```text
1. The process plants use to make food [2]
2. Water freezes at 0 degrees Celsius [1]
3. Any one: evaporation / condensation / precipitation [3]
```

Student scripts should use matching question numbers:

```text
1. Plants make food through photosynthesis.
2. 0 C
3. evaporation
```

The app uses fuzzy text matching. It is intended to speed up marking and identify likely matches, not replace final teacher judgment for open-ended answers.

## API

### JavaScript

```javascript
const form = new FormData()
form.append("threshold", "0.72")
form.append("memo", memoFile)
for (const file of testFiles) form.append("tests", file)

const response = await fetch("http://127.0.0.1:7860/api/mark", {
  method: "POST",
  body: form
})
const result = await response.json()
```

### Python

```python
import requests

files = [
    ("memo", open("memo.txt", "rb")),
    ("tests", open("test-1.txt", "rb")),
    ("tests", open("test-2.txt", "rb")),
]
response = requests.post(
    "http://127.0.0.1:7860/api/mark",
    data={"threshold": "0.72"},
    files=files,
    timeout=120,
)
print(response.json())
```

### Curl

```bash
curl -X POST http://127.0.0.1:7860/api/mark \
  -F threshold=0.72 \
  -F memo=@memo.txt \
  -F tests=@test-1.txt \
  -F tests=@test-2.txt
```

Download the latest CSV:

```bash
curl -o marking-results.csv http://127.0.0.1:7860/api/results/latest.csv
```
