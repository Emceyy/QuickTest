const app = document.querySelector("#app");
const brandSubtitle = document.querySelector("#brandSubtitle");
const homeButton = document.querySelector("#homeButton");
const wrongButton = document.querySelector("#wrongButton");
const reviewButton = document.querySelector("#reviewButton");
const reportButton = document.querySelector("#reportButton");

const state = {
  summary: null,
  wrongSummary: { test: 0, trial: 0, karma: 0 },
  categories: [],
  trials: [],
  mode: null,
  modeLabel: "",
  wrongBucket: null,
  questions: [],
  allQuestions: [],
  currentIndex: 0,
  answers: new Map(),
  savedQuestionIds: new Set(),
  sessionId: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
  karmaUsedIds: new Set(),
};

const letters = ["A", "B", "C", "D", "E"];

homeButton.addEventListener("click", () => renderHome());
wrongButton.addEventListener("click", () => renderWrongHub());
reviewButton.addEventListener("click", () => renderReview());
reportButton.addEventListener("click", () => renderReport());

function setLoading() {
  const tpl = document.querySelector("#loadingTemplate");
  app.replaceChildren(tpl.content.cloneNode(true));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function number(value) {
  return new Intl.NumberFormat("tr-TR").format(value ?? 0);
}

function scrollTop() {
  app.focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function init() {
  setLoading();
  const [summary, categories, trials, wrongSummary] = await Promise.all([
    api("/api/summary"),
    api("/api/categories"),
    api("/api/trials"),
    api("/api/wrong-summary"),
  ]);
  state.summary = summary;
  state.categories = categories;
  state.trials = trials;
  state.wrongSummary = wrongSummary;
  brandSubtitle.textContent = `${number(summary.totalQuestions)} soru`;
  renderHome();
}

function renderHome() {
  state.mode = null;
  state.wrongBucket = null;
  app.innerHTML = `
    <section class="hero-panel">
      <div>
        <p class="eyebrow">Güncel Bilgiler</p>
        <h1>Bugünkü çalışma akışın hazır.</h1>
        <p>Test, deneme ve karma modları aynı soru havuzundan çalışır; yanlış yaptıkların ayrıca takip edilir.</p>
      </div>
      <div class="toolbar-meta">
        <span class="pill">${number(state.summary.totalQuestions)} soru</span>
        <span class="pill bad">${number(state.wrongSummary.karma)} yanlış</span>
        <span class="pill warn">${number(state.summary.reviewCount)} kontrol</span>
      </div>
    </section>

    <section class="stats-grid" aria-label="Özet">
      <div class="stat"><span class="stat-value">${number(state.summary.questionBankQuestions)}</span><span class="stat-label">Soru Bankası</span></div>
      <div class="stat"><span class="stat-value">${number(state.summary.trialQuestions)}</span><span class="stat-label">Deneme Sorusu</span></div>
      <div class="stat"><span class="stat-value">${number(state.summary.categoryCount)}</span><span class="stat-label">Kategori</span></div>
      <div class="stat"><span class="stat-value">${number(state.summary.trialCount)}</span><span class="stat-label">Deneme</span></div>
    </section>

    <section class="mode-grid" aria-label="Modlar">
      <button class="mode-card" type="button" data-mode="test">
        <strong>Test</strong>
        <span>Kategori seçerek soru bankasından ilerle.</span>
      </button>
      <button class="mode-card" type="button" data-mode="trial">
        <strong>Deneme</strong>
        <span>1-100 arasından bir deneme çöz.</span>
      </button>
      <button class="mode-card" type="button" data-mode="karma">
        <strong>Karma</strong>
        <span>Tüm havuzu tekrar etmeden karıştır.</span>
      </button>
      <button class="mode-card" type="button" data-mode="wrong">
        <strong>Yanlışlar</strong>
        <span>${number(state.wrongSummary.karma)} soru tekrar bekliyor.</span>
      </button>
    </section>
  `;

  app.querySelector('[data-mode="test"]').addEventListener("click", renderCategorySelect);
  app.querySelector('[data-mode="trial"]').addEventListener("click", renderTrialSelect);
  app.querySelector('[data-mode="karma"]').addEventListener("click", startKarma);
  app.querySelector('[data-mode="wrong"]').addEventListener("click", renderWrongHub);
  scrollTop();
}

function renderCategorySelect() {
  app.innerHTML = `
    <section class="toolbar">
      <h1>Test</h1>
      <button class="secondary-button" type="button" id="backHome">Geri</button>
    </section>
    <section class="category-grid" aria-label="Kategoriler">
      ${state.categories
        .map(
          (category) => `
            <button class="category-card" type="button" data-category-id="${category.id}">
              <strong>${escapeHtml(category.title)}</strong>
              <span>${category.startQuestion}-${category.endQuestion} · ${category.questionCount} soru</span>
            </button>
          `
        )
        .join("")}
    </section>
  `;
  app.querySelector("#backHome").addEventListener("click", renderHome);
  app.querySelectorAll("[data-category-id]").forEach((button) => {
    button.addEventListener("click", () => startQuiz("test", Number(button.dataset.categoryId)));
  });
  scrollTop();
}

function renderTrialSelect() {
  app.innerHTML = `
    <section class="toolbar">
      <h1>Deneme</h1>
      <button class="secondary-button" type="button" id="backHome">Geri</button>
    </section>
    <section class="trial-grid" aria-label="Denemeler">
      ${state.trials
        .map(
          (trial) => `
            <button class="trial-button" type="button" data-trial-no="${trial.trialNo}">
              ${trial.trialNo}
            </button>
          `
        )
        .join("")}
    </section>
  `;
  app.querySelector("#backHome").addEventListener("click", renderHome);
  app.querySelectorAll("[data-trial-no]").forEach((button) => {
    button.addEventListener("click", () => startQuiz("trial", Number(button.dataset.trialNo)));
  });
  scrollTop();
}

async function startQuiz(mode, value) {
  setLoading();
  const path =
    mode === "test"
      ? `/api/questions?mode=test&categoryId=${value}`
      : `/api/questions?mode=trial&trialNo=${value}`;
  const questions = await api(path);
  state.mode = mode;
  state.modeLabel =
    mode === "test"
      ? state.categories.find((item) => item.id === value)?.title || "Test"
      : `Deneme ${value}`;
  state.questions = questions;
  state.currentIndex = 0;
  state.answers = new Map();
  state.savedQuestionIds = new Set();
  state.sessionId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  renderQuiz();
}

async function startKarma() {
  setLoading();
  const [questions, karmaState] = await Promise.all([
    api("/api/questions?mode=karma"),
    api("/api/karma-state"),
  ]);
  state.mode = "karma";
  state.modeLabel = "Karma";
  state.allQuestions = questions;
  state.questions = [];
  state.answers = new Map();
  state.savedQuestionIds = new Set();
  state.karmaUsedIds = new Set(karmaState.usedIds || []);
  state.sessionId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  pickNextKarmaQuestion();
}

function renderWrongHub() {
  state.mode = null;
  app.innerHTML = `
    <section class="toolbar">
      <h1>Yanlışlar</h1>
      <button class="secondary-button" type="button" id="backHome">Ana Ekran</button>
    </section>
    <section class="mode-grid" aria-label="Yanlış listeleri">
      <button class="mode-card" type="button" data-wrong-bucket="test">
        <strong>Test Yanlışları</strong>
        <span>${number(state.wrongSummary.test)} soru</span>
      </button>
      <button class="mode-card" type="button" data-wrong-bucket="trial">
        <strong>Deneme Yanlışları</strong>
        <span>${number(state.wrongSummary.trial)} soru</span>
      </button>
      <button class="mode-card" type="button" data-wrong-bucket="karma">
        <strong>Karma Yanlışları</strong>
        <span>${number(state.wrongSummary.karma)} soru</span>
      </button>
    </section>
  `;
  app.querySelector("#backHome").addEventListener("click", renderHome);
  app.querySelectorAll("[data-wrong-bucket]").forEach((button) => {
    button.addEventListener("click", () => startWrong(button.dataset.wrongBucket));
  });
  scrollTop();
}

async function startWrong(bucket) {
  setLoading();
  const questions = await api(`/api/questions?mode=wrong&bucket=${bucket}`);
  const labels = {
    test: "Test Yanlışları",
    trial: "Deneme Yanlışları",
    karma: "Karma Yanlışları",
  };
  if (!questions.length) {
    app.innerHTML = `
      <section class="toolbar">
        <h1>${labels[bucket]}</h1>
        <button class="secondary-button" type="button" id="backWrongHub">Geri</button>
      </section>
      <section class="empty-state">
        <div>
          <h2>Burada bekleyen yanlış yok.</h2>
          <p>Yeni yanlış yaptığında buraya otomatik düşecek.</p>
        </div>
      </section>
    `;
    app.querySelector("#backWrongHub").addEventListener("click", renderWrongHub);
    scrollTop();
    return;
  }
  state.mode = "wrong";
  state.wrongBucket = bucket;
  state.modeLabel = labels[bucket];
  state.questions = questions;
  state.currentIndex = 0;
  state.answers = new Map();
  state.savedQuestionIds = new Set();
  state.sessionId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  renderQuiz();
}

function pickNextKarmaQuestion() {
  const usedInSession = new Set(state.questions.map((question) => question.id));
  let remaining = state.allQuestions.filter(
    (question) => !state.karmaUsedIds.has(question.id) && !usedInSession.has(question.id)
  );
  if (!remaining.length) {
    state.karmaUsedIds = new Set();
    remaining = state.allQuestions.filter((question) => !usedInSession.has(question.id));
  }
  const next = remaining[Math.floor(Math.random() * remaining.length)];
  state.questions.push(next);
  state.currentIndex = state.questions.length - 1;
  renderQuiz();
}

function renderQuiz() {
  const question = state.questions[state.currentIndex];
  const selected = state.answers.get(question.id);
  const total = state.questions.length;
  const answeredCount = state.answers.size;
  const progress = state.mode === "karma"
    ? Math.min(100, Math.round((state.karmaUsedIds.size / Math.max(1, state.allQuestions.length)) * 100))
    : Math.round(((state.currentIndex + 1) / Math.max(1, total)) * 100);

  app.innerHTML = `
    <section class="toolbar">
      <h1>${escapeHtml(state.modeLabel)}</h1>
      <div class="toolbar-meta">
        <span class="pill">${escapeHtml(question.display)}</span>
        ${question.categoryTitle ? `<span class="pill">${escapeHtml(question.categoryTitle)}</span>` : ""}
        ${question.needsReview ? `<span class="pill warn">Kontrol</span>` : ""}
      </div>
    </section>

    <section class="question-panel">
      <div class="question-head">
        <p class="question-title">${state.mode === "karma" ? `Oturum: ${answeredCount}` : `${state.currentIndex + 1} / ${total}`}</p>
        <div class="question-source">
          <span class="pill">${escapeHtml(question.sourceLabel)}</span>
          <span class="pill">Sayfa ${question.pageNo}</span>
        </div>
      </div>

      <p class="question-text">${escapeHtml(question.prompt)}</p>
      <div class="options">
        ${letters
          .map(
            (letter) => `
              <button class="option-button ${selected === letter ? "selected" : ""}" type="button" data-answer="${letter}">
                <span class="option-letter">${letter}</span>
                <span>${escapeHtml(question.options[letter] || "")}</span>
              </button>
            `
          )
          .join("")}
      </div>

      <div class="quiz-footer">
        <div class="progress-wrap">
          <div class="progress-label">
            <span>${state.mode === "karma" ? "Karma turu" : state.mode === "wrong" ? "Yanlış tekrarı" : "İlerleme"}</span>
            <span>${progress}%</span>
          </div>
          <div class="progress-bar"><span style="width:${progress}%"></span></div>
        </div>
        <div class="button-row">
          ${state.currentIndex > 0 && state.mode !== "karma" ? '<button class="secondary-button" type="button" id="prevQuestion">Önceki</button>' : ""}
          <button class="secondary-button" type="button" id="blankQuestion">Boş Bırak</button>
          <button class="primary-button" type="button" id="nextQuestion">${nextLabel()}</button>
          ${state.answers.size ? '<button class="ghost-button" type="button" id="showResults">Sonuç</button>' : ""}
        </div>
      </div>
    </section>
  `;

  app.querySelectorAll("[data-answer]").forEach((button) => {
    button.addEventListener("click", () => {
      state.answers.set(question.id, button.dataset.answer);
      renderQuiz();
    });
  });
  const prev = app.querySelector("#prevQuestion");
  if (prev) prev.addEventListener("click", () => {
    state.currentIndex = Math.max(0, state.currentIndex - 1);
    renderQuiz();
  });
  app.querySelector("#blankQuestion").addEventListener("click", () => {
    state.answers.set(question.id, null);
    renderQuiz();
  });
  app.querySelector("#nextQuestion").addEventListener("click", async () => {
    if (!state.answers.has(question.id)) return;
    if (state.mode === "karma") {
      const selectedAnswer = state.answers.get(question.id);
      await saveAttempts([{
        question,
        selected: selectedAnswer,
        isCorrect: selectedAnswer === question.correctAnswer,
      }]);
      await api("/api/karma-used", {
        method: "POST",
        body: JSON.stringify({ questionId: question.id }),
      }).then((payload) => {
        state.karmaUsedIds = new Set(payload.usedIds || []);
      });
      pickNextKarmaQuestion();
      return;
    }
    if (state.currentIndex + 1 >= state.questions.length) {
      renderResults();
    } else {
      state.currentIndex += 1;
      renderQuiz();
    }
  });
  const showResults = app.querySelector("#showResults");
  if (showResults) showResults.addEventListener("click", renderResults);
  scrollTop();
}

function nextLabel() {
  if (state.mode === "karma") return "Sonraki";
  return state.currentIndex + 1 >= state.questions.length ? "Bitir" : "Sonraki";
}

async function saveAttempts(results) {
  const unsaved = results.filter((item) => !state.savedQuestionIds.has(item.question.id));
  if (!unsaved.length) return;
  await api("/api/attempts", {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.sessionId,
      mode: state.mode,
      answers: unsaved.map((item) => ({
        questionId: item.question.id,
        selectedAnswer: item.selected,
      })),
    }),
  });
  unsaved.forEach((item) => state.savedQuestionIds.add(item.question.id));
  state.wrongSummary = await api("/api/wrong-summary");
}

function getResults() {
  return state.questions
    .filter((question) => state.answers.has(question.id))
    .map((question) => {
      const selected = state.answers.get(question.id);
      const isCorrect = selected === question.correctAnswer;
      return { question, selected, isCorrect };
    });
}

async function renderResults() {
  const results = getResults();
  if (results.length) await saveAttempts(results);
  const correct = results.filter((item) => item.isCorrect).length;
  const wrong = results.filter((item) => !item.isCorrect && item.selected).length;
  const empty = results.filter((item) => !item.selected).length;

  app.innerHTML = `
    <section class="toolbar">
      <h1>Sonuç</h1>
      <div class="toolbar-meta">
        <span class="pill good">${correct} doğru</span>
        <span class="pill bad">${wrong} yanlış</span>
        <span class="pill warn">${empty} boş</span>
      </div>
    </section>

    <section class="stats-grid" aria-label="Sonuç özeti">
      <div class="stat"><span class="stat-value">${results.length}</span><span class="stat-label">Toplam</span></div>
      <div class="stat"><span class="stat-value">${correct}</span><span class="stat-label">Doğru</span></div>
      <div class="stat"><span class="stat-value">${wrong}</span><span class="stat-label">Yanlış</span></div>
      <div class="stat"><span class="stat-value">${empty}</span><span class="stat-label">Boş</span></div>
    </section>

    <div class="button-row" style="margin-bottom: 16px;">
      <button class="secondary-button" type="button" id="backHomeResult">Ana Ekran</button>
      ${results.some((item) => item.selected && !item.isCorrect) ? '<button class="primary-button" type="button" id="retryWrong">Yanlışları Çöz</button>' : ""}
    </div>

    <section class="results-list">
      ${results.map(renderResultCard).join("")}
    </section>
  `;
  app.querySelector("#backHomeResult").addEventListener("click", renderHome);
  const retryWrong = app.querySelector("#retryWrong");
  if (retryWrong) retryWrong.addEventListener("click", () => {
    state.questions = results.filter((item) => item.selected && !item.isCorrect).map((item) => item.question);
    state.answers = new Map();
    state.savedQuestionIds = new Set();
    state.currentIndex = 0;
    state.modeLabel = "Yanlışlar";
    renderQuiz();
  });
  scrollTop();
}

function renderResultCard(item, index) {
  const { question, selected, isCorrect } = item;
  return `
    <article class="result-card">
      <div class="result-title">
        <strong>${index + 1}. ${escapeHtml(question.display)}</strong>
        <span class="pill ${isCorrect ? "good" : "bad"}">${isCorrect ? "Doğru" : "Yanlış"}</span>
      </div>
      <p class="result-prompt">${escapeHtml(question.prompt)}</p>
      <div class="options">
        ${letters
          .map((letter) => {
            const cls = letter === question.correctAnswer ? "correct" : selected === letter ? "wrong" : "";
            return `
              <div class="option-button ${cls}">
                <span class="option-letter">${letter}</span>
                <span>${escapeHtml(question.options[letter] || "")}</span>
              </div>
            `;
          })
          .join("")}
      </div>
      <div class="answer-line">
        <span class="pill">İşaretlenen: ${selected || "Boş"}</span>
        <span class="pill good">Doğru cevap: ${question.correctAnswer}</span>
      </div>
      ${question.explanation ? `<div class="explanation">${escapeHtml(question.explanation)}</div>` : ""}
    </article>
  `;
}

async function renderReview() {
  setLoading();
  const questions = await api("/api/review?limit=500");
  app.innerHTML = `
    <section class="toolbar">
      <h1>Kontrol</h1>
      <div class="toolbar-meta">
        <span class="pill warn">${questions.length} kayıt</span>
      </div>
    </section>
    <section class="review-list">
      ${questions.length ? questions.map(renderReviewCard).join("") : '<div class="empty-state"><p>Kayıt yok</p></div>'}
    </section>
  `;
  app.querySelectorAll("[data-save-question]").forEach((button) => {
    button.addEventListener("click", () => saveReviewQuestion(Number(button.dataset.saveQuestion)));
  });
  scrollTop();
}

function renderReviewCard(question) {
  return `
    <article class="review-card" id="review-${question.id}">
      <div class="review-title">
        <strong>${escapeHtml(question.display)} · ${escapeHtml(question.sourceLabel)} · Sayfa ${question.pageNo}</strong>
        <span class="pill warn">Kontrol</span>
      </div>
      <div class="answer-line">
        ${(question.reviewNotes || []).map((note) => `<span class="pill warn">${escapeHtml(note)}</span>`).join("")}
      </div>
      <div class="form-grid" style="margin-top: 12px;">
        <label>Soru
          <textarea data-field="prompt">${escapeHtml(question.prompt)}</textarea>
        </label>
        <div class="option-edit-grid">
          ${letters
            .map(
              (letter) => `
                <label>${letter}
                  <textarea data-option="${letter}">${escapeHtml(question.options[letter] || "")}</textarea>
                </label>
              `
            )
            .join("")}
        </div>
        <label>Doğru Cevap
          <select data-field="correctAnswer">
            ${letters.map((letter) => `<option value="${letter}" ${question.correctAnswer === letter ? "selected" : ""}>${letter}</option>`).join("")}
          </select>
        </label>
        <label>Çözüm
          <textarea data-field="explanation">${escapeHtml(question.explanation || "")}</textarea>
        </label>
        <details>
          <summary>Ham PDF metni</summary>
          <pre>${escapeHtml(question.rawText || "")}</pre>
        </details>
        <div class="button-row">
          <button class="primary-button" type="button" data-save-question="${question.id}">Kaydet</button>
          <label style="display:flex; align-items:center; gap:8px; color: var(--muted);">
            <input type="checkbox" data-field="needsReview" checked />
            Kontrolde kalsın
          </label>
        </div>
      </div>
    </article>
  `;
}

async function saveReviewQuestion(id) {
  const card = app.querySelector(`#review-${id}`);
  const payload = {
    prompt: card.querySelector('[data-field="prompt"]').value,
    correctAnswer: card.querySelector('[data-field="correctAnswer"]').value,
    explanation: card.querySelector('[data-field="explanation"]').value,
    needsReview: card.querySelector('[data-field="needsReview"]').checked,
    options: {},
  };
  card.querySelectorAll("[data-option]").forEach((field) => {
    payload.options[field.dataset.option] = field.value;
  });
  const updated = await api(`/api/questions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  const wrapper = document.createElement("div");
  wrapper.innerHTML = renderReviewCard(updated).trim();
  card.replaceWith(wrapper.firstElementChild);
  app.querySelector(`#review-${id} [data-save-question]`).addEventListener("click", () => saveReviewQuestion(id));
}

async function renderReport() {
  setLoading();
  const report = await api("/api/report");
  app.innerHTML = `
    <section class="toolbar">
      <h1>Rapor</h1>
      <button class="danger-button" type="button" id="reimportButton">Tekrar Aktar</button>
    </section>
    <section class="report-panel">
      <pre>${escapeHtml(JSON.stringify(report, null, 2))}</pre>
    </section>
  `;
  app.querySelector("#reimportButton").addEventListener("click", async () => {
    setLoading();
    await api("/api/reimport", { method: "POST", body: "{}" });
    await init();
  });
  scrollTop();
}

init().catch((error) => {
  app.innerHTML = `
    <section class="empty-state">
      <div>
        <h1>Başlatılamadı</h1>
        <pre>${escapeHtml(error.message)}</pre>
      </div>
    </section>
  `;
});
