const form = document.querySelector("#marking-form");
const accessPanel = document.querySelector("#access-panel");
const accessForm = document.querySelector("#access-form");
const accessInput = document.querySelector("#access-code");
const accessStatus = document.querySelector("#access-status");
const results = document.querySelector("#results");
const statusBox = document.querySelector("#status");
const threshold = form.querySelector("input[name='threshold']");
const thresholdValue = document.querySelector("#threshold-value");
const resultTitle = document.querySelector("#result-title");
const downloadLink = document.querySelector("#download-link");
let accessCodeRequired = false;
let accessCode = sessionStorage.getItem("markingAppAccessCode") || "";

function authHeaders() {
  return accessCode ? { "X-Marking-App-Passcode": accessCode } : {};
}

function updateAccessPanel() {
  accessPanel.hidden = !accessCodeRequired || Boolean(accessCode);
}

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
  downloadLink.href = accessCode
    ? `/api/results/latest.csv?access_code=${encodeURIComponent(accessCode)}`
    : "/api/results/latest.csv";
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

accessForm.addEventListener("submit", (event) => {
  event.preventDefault();
  accessCode = accessInput.value.trim();
  sessionStorage.setItem("markingAppAccessCode", accessCode);
  accessStatus.textContent = "";
  updateAccessPanel();
});

async function loadConfig() {
  const response = await fetch("/api/config");
  if (!response.ok) {
    return;
  }
  const config = await response.json();
  accessCodeRequired = Boolean(config.access_code_required);
  updateAccessPanel();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (accessCodeRequired && !accessCode) {
    accessStatus.textContent = "Enter the access code before marking files.";
    updateAccessPanel();
    return;
  }
  results.innerHTML = "";
  downloadLink.hidden = true;
  statusBox.textContent = "Marking uploaded scripts...";
  resultTitle.textContent = "Working";

  const response = await fetch("/api/mark", {
    method: "POST",
    headers: authHeaders(),
    body: new FormData(form),
  });
  const payload = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      sessionStorage.removeItem("markingAppAccessCode");
      accessCode = "";
      accessStatus.textContent = payload.error || "Enter the teacher access code.";
      updateAccessPanel();
    }
    resultTitle.textContent = "Could not mark files";
    statusBox.textContent = payload.error || "An unknown error occurred.";
    return;
  }
  renderResults(payload);
});

loadConfig();
