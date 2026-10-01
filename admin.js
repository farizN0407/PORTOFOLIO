const authLayout = document.querySelector("#auth-layout");
const dashboard = document.querySelector("#dashboard");
const loginForm = document.querySelector("#login-form");
const loginMessage = document.querySelector("#login-message");
const entryList = document.querySelector("#entry-list");
const emptyState = document.querySelector("#empty-state");
const dialog = document.querySelector("#entry-dialog");
const entryForm = document.querySelector("#entry-form");
const fieldGrid = document.querySelector("#field-grid");
const entryMessage = document.querySelector("#entry-message");

const schema = {
  projects: {
    title: "Projects",
    fields: [
      ["title", "Project title", "text", true, true],
      ["category", "Category", "text", false, false],
      ["summary", "Short description", "textarea", true, true],
      ["description", "Detailed description", "textarea", true, false],
      ["tools", "Tools / technologies", "text", true, false],
      ["github_url", "GitHub URL", "url", false, false],
      ["external_url", "External URL", "url", false, false],
      ["featured", "Featured project", "checkbox", false, false],
    ],
    detail: (item) => item.summary,
    category: (item) => item.category || "PROJECT",
  },
  certifications: {
    title: "Certifications",
    fields: [
      ["name", "Certification name", "text", true, true],
      ["issuer", "Issuer", "text", false, false],
      ["date", "Date / year", "text", false, false],
      ["credential_url", "Credential URL", "url", false, false],
      ["credential_id", "Credential ID", "text", false, false],
      ["description", "Description", "textarea", true, false],
    ],
    detail: (item) => [item.issuer, item.date].filter(Boolean).join(" · "),
    category: () => "CERTIFICATION",
  },
  activities: {
    title: "Activities",
    fields: [
      ["name", "Organization / activity", "text", true, true],
      ["role", "Role", "text", false, false],
      ["start_date", "Start date", "text", false, false],
      ["end_date", "End date", "text", false, false],
      ["description", "Description", "textarea", true, false],
      ["url", "URL", "url", false, false],
    ],
    detail: (item) => [item.role, item.start_date, item.end_date].filter(Boolean).join(" · "),
    category: () => "ACTIVITY",
  },
};

let currentSection = "projects";
let csrfToken = "";
let items = [];
let editingId = null;

async function api(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body) headers.set("Content-Type", "application/json");
  if (options.method && options.method !== "GET") headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(url, { ...options, headers, credentials: "same-origin" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function showDashboard(email) {
  authLayout.classList.add("hidden");
  dashboard.classList.remove("hidden");
  document.querySelector("#admin-email").textContent = email;
  loadSection(currentSection);
}

async function resumeSession() {
  try {
    const session = await api("/api/admin/session");
    csrfToken = session.csrf;
    showDashboard(session.email);
  } catch {
    authLayout.classList.remove("hidden");
  }
}

async function loadSection(name) {
  currentSection = name;
  const currentSchema = schema[name];
  document.querySelector("#section-title").textContent = currentSchema.title;
  document.querySelectorAll("#section-nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === name);
  });
  entryList.replaceChildren();
  try {
    items = await api(`/api/admin/${name}`);
    document.querySelector("#item-count").textContent = `${items.length} ${items.length === 1 ? "entry" : "entries"}`;
    emptyState.classList.toggle("hidden", items.length > 0);
    items.forEach((item) => entryList.append(makeEntryCard(item, currentSchema)));
  } catch (error) {
    document.querySelector("#item-count").textContent = error.message;
  }
}

function makeEntryCard(item, currentSchema) {
  const card = document.createElement("article");
  card.className = "entry-card";
  const main = document.createElement("div");
  main.className = "entry-main";
  const category = document.createElement("span");
  category.className = "entry-kicker";
  category.textContent = currentSchema.category(item);
  const title = document.createElement("h2");
  title.className = "entry-title";
  title.textContent = item.title || item.name || "Untitled";
  const description = document.createElement("p");
  description.className = "entry-description";
  description.textContent = currentSchema.detail(item) || "No additional details";
  main.append(category, title, description);
  const status = document.createElement("div");
  status.className = `entry-status${item.is_published ? "" : " draft"}`;
  const dot = document.createElement("i");
  dot.className = "status-dot";
  status.append(dot, document.createTextNode(item.is_published ? "PUBLISHED" : "HIDDEN"));
  const actions = document.createElement("div");
  actions.className = "entry-actions";
  const edit = document.createElement("button");
  edit.type = "button";
  edit.textContent = "EDIT";
  edit.addEventListener("click", () => openDialog(item));
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "delete";
  remove.textContent = "DELETE";
  remove.addEventListener("click", () => deleteItem(item.id));
  actions.append(edit, remove);
  card.append(main, status, actions);
  return card;
}

function buildFields() {
  fieldGrid.replaceChildren();
  schema[currentSection].fields.forEach(([name, label, type, full]) => {
    const wrapper = document.createElement("label");
    wrapper.className = `field${full ? " full" : ""}`;
    wrapper.append(document.createTextNode(label));
    if (type === "checkbox") {
      const input = document.createElement("input");
      input.type = type;
      input.name = name;
      wrapper.append(input);
    } else {
      const input = document.createElement(type === "textarea" ? "textarea" : "input");
      if (type !== "textarea") input.type = type;
      input.name = name;
      if (type === "url") input.placeholder = "https://";
      input.maxLength = type === "url" ? 2048 : 8000;
      wrapper.append(input);
    }
    fieldGrid.append(wrapper);
  });
}

function openDialog(item = null) {
  editingId = item?.id ?? null;
  entryForm.reset();
  buildFields();
  entryMessage.textContent = "";
  document.querySelector("#dialog-kicker").textContent = item ? "EDIT ENTRY" : "NEW ENTRY";
  document.querySelector("#dialog-title").textContent = `${item ? "Edit" : "Add"} ${schema[currentSection].title.toLowerCase().replace(/s$/, "")}`;
  if (item) {
    Object.entries(item).forEach(([name, value]) => {
      const input = entryForm.elements.namedItem(name);
      if (!input) return;
      if (input.type === "checkbox") input.checked = Boolean(value);
      else input.value = value ?? "";
    });
  }
  dialog.showModal();
}

async function deleteItem(id) {
  const item = items.find((candidate) => candidate.id === id);
  if (!item || !window.confirm(`Delete “${item.title || item.name}”? This cannot be undone.`)) return;
  try {
    await api(`/api/admin/${currentSection}/${id}`, { method: "DELETE" });
    await loadSection(currentSection);
  } catch (error) {
    window.alert(error.message);
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginMessage.textContent = "Signing in…";
  const form = new FormData(loginForm);
  try {
    const session = await api("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
    });
    csrfToken = session.csrf;
    loginForm.reset();
    showDashboard(session.email);
  } catch (error) {
    loginMessage.textContent = error.message;
  }
});

document.querySelectorAll("#section-nav button").forEach((button) => {
  button.addEventListener("click", () => loadSection(button.dataset.section));
});
document.querySelector("#new-button").addEventListener("click", () => openDialog());
document.querySelector("#close-dialog").addEventListener("click", () => dialog.close());
document.querySelector("#cancel-dialog").addEventListener("click", () => dialog.close());

entryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  entryMessage.textContent = "";
  const data = new FormData(entryForm);
  const payload = {};
  schema[currentSection].fields.forEach(([name, , ,]) => {
    const input = entryForm.elements.namedItem(name);
    payload[name] = input.type === "checkbox" ? input.checked : data.get(name);
  });
  payload.is_published = entryForm.elements.namedItem("is_published").checked;
  payload.sort_order = Number(data.get("sort_order") || 0);
  try {
    await api(`/api/admin/${currentSection}${editingId ? `/${editingId}` : ""}`, {
      method: editingId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    dialog.close();
    await loadSection(currentSection);
  } catch (error) {
    entryMessage.textContent = error.message;
  }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try {
    await api("/api/admin/logout", { method: "POST", body: "{}" });
  } finally {
    window.location.reload();
  }
});

resumeSession();
