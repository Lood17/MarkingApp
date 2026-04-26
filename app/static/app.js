const form = document.querySelector("#marking-form");
const results = document.querySelector("#results");
const statusBox = document.querySelector("#status");
const threshold = form.querySelector("input[name='threshold']");
const thresholdValue = document.querySelector("#threshold-value");
const resultTitle = document.querySelector("#result-title");
const downloadLink = document.querySelector("#download-link");

function updateThreshold() {
  thresholdValue.value = `${Math.round(Number(threshold.value) * 100)}%`;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function renderResults(payload) {
  const marked = payload.results || [];
  resultTitle.textContent = `${marked.length} script${marked.length === 1 ? "" : "s"} marked`;
  downloadLink.hidden = marked.length === 0;
  statusBox.textContent = `Memo parsed into ${payload.memo_items} markable item${payload.memo_items === 1 ? "" : "s"}.`;
  results.innerHTML = marked.map((submission) => `
    <article class="submission">
      <header>
        <div>
          <h3>${escapeHtml(submission.filename)}</h3>
          <p>${submission.score} / ${submission.possible}</p>
        </div>
        <strong>${submission.percent}%</strong>
      </header>
      <div class="questions">
        ${submission.questions.map((row) => `
          <details>
            <summary>
              <span>Q${escapeHtml(row.question)}</span>
              <span>${row.score} / ${row.points}</span>
              <span>${Math.round(row.confidence * 100)}%</span>
            </summary>
            <dl>
              <dt>Expected</dt>
              <dd>${escapeHtml(row.expected)}</dd>
              <dt>Student</dt>
              <dd>${escapeHtml(row.student_answer || "No answer found")}</dd>
              <dt>Comment</dt>
              <dd>${escapeHtml(row.comment)}</dd>
            </dl>
          </details>
        `).join("")}
      </div>
    </article>
  `).join("");
}

threshold.addEventListener("input", updateThreshold);
updateThreshold();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  results.innerHTML = "";
  downloadLink.hidden = true;
  statusBox.textContent = "Marking uploaded scripts...";
  resultTitle.textContent = "Working";

  const response = await fetch("/api/mark", {
    method: "POST",
    body: new FormData(form),
  });
  const payload = await response.json();
  if (!response.ok) {
    resultTitle.textContent = "Could not mark files";
    statusBox.textContent = payload.error || "An unknown error occurred.";
    return;
  }
  renderResults(payload);
});
