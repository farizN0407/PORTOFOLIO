const authLayout = document.querySelector("#auth-layout");
const setupLayout = document.querySelector("#setup-layout");
const checkingState = document.querySelector("#checking-state");
const dashboard = document.querySelector("#dashboard");
const loginForm = document.querySelector("#login-form");
const loginMessage = document.querySelector("#login-message");
const setupForm = document.querySelector("#setup-form");
const setupMessage = document.querySelector("#setup-message");
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
      ["slug", "Public page slug (auto from title when blank)", "text", true, false],
      ["category", "Category", "text", false, false],
      ["summary", "Short description", "textarea", true, true],
      ["description", "Detailed description", "textarea", true, false],
      ["tools", "Tools / technologies", "text", true, false],
      ["github_url", "GitHub URL", "url", false, false],
      ["external_url", "External URL", "url", false, false],
      ["featured", "Featured project", "checkbox", false, false],
      ["thumbnail_id", "Project thumbnail · image only", "file", true, false],
    ],
    fileField: "thumbnail_id",
    fileAccept: "image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp",
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
      ["certificate_file_id", "Certificate file", "file", true, false],
    ],
    fileField: "certificate_file_id",
    fileAccept: "application/pdf,image/png,image/jpeg,image/webp",
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
    fileField: null,
    detail: (item) => [item.role, item.start_date, item.end_date].filter(Boolean).join(" · "),
    category: () => "ACTIVITY",
  },
};

let currentSection = "projects";
let csrfToken = "";
let items = [];
let editingId = null;
let thumbnailPreviewUrl = "";

const thumbnailMimeByExtension = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
};

function isValidThumbnail(file) {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  return thumbnailMimeByExtension[extension] === file.type;
}

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
  checkingState.classList.add("hidden");
  setupLayout.classList.add("hidden");
  authLayout.classList.add("hidden");
  dashboard.classList.remove("hidden");
  document.querySelector("#admin-email").textContent = email;
  loadSection(currentSection);
}

async function initializeAdminPage() {
  try {
    const session = await api("/api/admin/session");
    csrfToken = session.csrf;
    showDashboard(session.email);
  } catch {
    try {
      const status = await api("/api/admin/status");
      checkingState.classList.add("hidden");
      if (status.setup_required) {
        csrfToken = status.setup_csrf;
        setupLayout.classList.remove("hidden");
      } else {
        authLayout.classList.remove("hidden");
      }
    } catch (error) {
      checkingState.replaceChildren(document.createTextNode(`Unable to load admin page: ${error.message}`));
    }
  }
}

setupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setupMessage.textContent = "Creating admin account…";
  const form = new FormData(setupForm);
  const email = String(form.get("email") || "").trim().toLowerCase();
  const password = String(form.get("password") || "");
  const passwordConfirmation = String(form.get("password_confirmation") || "");
  if (password !== passwordConfirmation) {
    setupMessage.textContent = "Passwords do not match.";
    return;
  }
  try {
    await api("/api/admin/setup", {
      method: "POST",
      body: JSON.stringify({ email, password, password_confirmation: passwordConfirmation }),
    });
    csrfToken = "";
    setupForm.reset();
    setupLayout.classList.add("hidden");
    authLayout.classList.remove("hidden");
    loginForm.elements.namedItem("email").value = email;
    loginMessage.textContent = "Admin account created. Sign in to continue.";
    loginForm.elements.namedItem("password").focus();
  } catch (error) {
    setupMessage.textContent = error.message;
    if (error.message === "Admin setup has already been completed") {
      csrfToken = "";
      setupLayout.classList.add("hidden");
      authLayout.classList.remove("hidden");
    }
  }
});

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

async function loadProjectAttachments(projectId) {
  const panel = document.querySelector("#writeup-panel");
  if (currentSection !== "projects" || !projectId) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  document.querySelector("#writeup-message").textContent = "";
  const list = document.querySelector("#writeup-list");
  list.replaceChildren();
  try {
    const attachments = await api(`/api/admin/projects/${projectId}/attachments`);
    document.querySelector("#writeup-hint").textContent = attachments.length ? `${attachments.length} attached file${attachments.length === 1 ? "" : "s"}` : "No write-ups attached yet.";
    attachments.forEach((attachment) => list.append(renderProjectAttachment(projectId, attachment)));
  } catch (error) {
    document.querySelector("#writeup-message").textContent = error.message;
  }
}

function renderProjectAttachment(projectId, attachment) {
  const row = document.createElement("div");
  row.className = "writeup-row";
  const fields = document.createElement("div");
  fields.className = "writeup-row-fields";
  const title = document.createElement("input");
  title.type = "text";
  title.maxLength = 240;
  title.value = attachment.title;
  title.setAttribute("aria-label", "Attachment title");
  const order = document.createElement("input");
  order.type = "number";
  order.value = attachment.display_order;
  order.setAttribute("aria-label", "Display order");
  fields.append(title, order);
  const actions = document.createElement("div");
  actions.className = "writeup-row-actions";
  const open = document.createElement("a");
  open.href = `/api/admin/files/${attachment.file_id}`;
  open.target = "_blank";
  open.rel = "noreferrer";
  open.textContent = "OPEN";
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = "SAVE";
  save.addEventListener("click", async () => {
    try {
      await api(`/api/admin/projects/${projectId}/attachments/${attachment.id}`, {
        method: "PUT", body: JSON.stringify({ title: title.value, display_order: Number(order.value || 0) }),
      });
      await loadProjectAttachments(projectId);
    } catch (error) { document.querySelector("#writeup-message").textContent = error.message; }
  });
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "delete";
  remove.textContent = "DELETE";
  remove.addEventListener("click", async () => {
    if (!window.confirm(`Delete “${attachment.title}”?`)) return;
    try {
      await api(`/api/admin/projects/${projectId}/attachments/${attachment.id}`, { method: "DELETE" });
      await loadProjectAttachments(projectId);
    } catch (error) { document.querySelector("#writeup-message").textContent = error.message; }
  });
  actions.append(open, save, remove);
  row.append(fields, actions);
  const filename = document.createElement("small");
  filename.textContent = attachment.original_name;
  row.append(filename);
  return row;
}

document.querySelector("#writeup-files").addEventListener("change", async (event) => {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!editingId || currentSection !== "projects" || !files.length) return;
  const message = document.querySelector("#writeup-message");
  message.textContent = "Uploading attachments…";
  try {
    const current = await api(`/api/admin/projects/${editingId}/attachments`);
    for (const [index, file] of files.entries()) {
      if (file.size > 5 * 1024 * 1024) throw new Error(`${file.name} is larger than 5 MB`);
      const response = await fetch(`/api/admin/projects/${editingId}/attachments`, {
        method: "POST", body: file, credentials: "same-origin",
        headers: {
          "Content-Type": file.type,
          "X-File-Name": encodeURIComponent(file.name),
          "X-Attachment-Title": encodeURIComponent(file.name.replace(/\.[^.]+$/, "")),
          "X-Display-Order": String(current.length + index),
          "X-CSRF-Token": csrfToken,
        },
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || `${file.name} upload failed`);
    }
    message.textContent = "Attachments uploaded.";
    await loadProjectAttachments(editingId);
  } catch (error) { message.textContent = error.message; }
});

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
  if (item.attachment_name && (item.thumbnail_id || item.certificate_file_id)) {
    const attachment = document.createElement("a");
    const fileId = item.thumbnail_id || item.certificate_file_id;
    attachment.className = "entry-attachment";
    attachment.href = `/api/admin/files/${fileId}`;
    attachment.target = "_blank";
    attachment.rel = "noreferrer";
    attachment.textContent = `FILE · ${item.attachment_name}`;
    main.append(attachment);
  }
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
    const wrapper = document.createElement(type === "file" ? "div" : "label");
    wrapper.className = `field${full ? " full" : ""}`;
    wrapper.append(document.createTextNode(label));
    if (type === "file") {
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = name;
      const input = document.createElement("input");
      input.type = "file";
      input.name = "attachment_upload";
      input.accept = schema[currentSection].fileAccept;
      input.className = "file-input";
      const status = document.createElement("p");
      status.className = "attachment-status";
      status.id = "attachment-status";
      const isProjectThumbnail = currentSection === "projects" && name === "thumbnail_id";
      status.textContent = isProjectThumbnail
        ? "Image only: PNG, JPG, JPEG, or WEBP · up to 5 MB. PDFs belong in Write-ups / Attachments below."
        : "Choose a PNG, JPG, WEBP, or PDF up to 5 MB.";
      const preview = isProjectThumbnail ? document.createElement("img") : null;
      if (preview) {
        preview.className = "thumbnail-preview hidden";
        preview.alt = "Project thumbnail preview";
        preview.hidden = true;
        preview.style.maxWidth = "180px";
        preview.style.maxHeight = "115px";
        preview.style.objectFit = "cover";
        preview.style.border = "1px solid rgba(255,255,255,.2)";
        preview.style.marginTop = "8px";
      }
      input.addEventListener("change", () => {
        const selected = input.files?.[0];
        if (selected) {
          if (isProjectThumbnail && !isValidThumbnail(selected)) {
            status.textContent = "Thumbnail must be an image (PNG, JPG, JPEG, or WEBP).";
            preview.classList.add("hidden");
            preview.hidden = true;
            return;
          }
          if (isProjectThumbnail) {
            if (thumbnailPreviewUrl) URL.revokeObjectURL(thumbnailPreviewUrl);
            thumbnailPreviewUrl = URL.createObjectURL(selected);
            preview.src = thumbnailPreviewUrl;
            preview.classList.remove("hidden");
            preview.hidden = false;
          }
          status.textContent = `Ready to upload: ${selected.name}`;
          remove.checked = false;
        }
      });
      const removeLabel = document.createElement("label");
      removeLabel.className = "remove-file-row";
      const remove = document.createElement("input");
      remove.type = "checkbox";
      remove.name = "remove_attachment";
      remove.addEventListener("change", () => {
        if (remove.checked) {
          input.value = "";
          status.textContent = "The attached file will be removed when you save.";
          if (preview) {
            preview.classList.add("hidden");
            preview.hidden = true;
          }
        } else if (!input.files?.length) {
          if (preview && hidden.value) {
            preview.src = `/api/admin/files/${hidden.value}`;
            preview.classList.remove("hidden");
            preview.hidden = false;
            status.textContent = "Current thumbnail will be kept.";
          } else {
            status.textContent = isProjectThumbnail
              ? "Image only: PNG, JPG, JPEG, or WEBP · up to 5 MB. PDFs belong in Write-ups / Attachments below."
              : "No new file selected.";
          }
        }
      });
      removeLabel.append(remove, document.createTextNode(isProjectThumbnail ? "Remove current thumbnail" : "Remove attached file"));
      wrapper.append(hidden, input, status);
      if (preview) wrapper.append(preview);
      wrapper.append(removeLabel);
    } else if (type === "checkbox") {
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
    const fileField = schema[currentSection].fileField;
    if (fileField && item[fileField]) {
      const status = document.querySelector("#attachment-status");
      const link = document.createElement("a");
      link.href = `/api/admin/files/${item[fileField]}`;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = item.attachment_name || "View attached file";
      status.replaceChildren(document.createTextNode("Current file: "), link);
      if (currentSection === "projects") {
        const preview = document.querySelector(".thumbnail-preview");
        if (preview) {
          preview.src = `/api/admin/files/${item[fileField]}`;
          preview.classList.remove("hidden");
          preview.hidden = false;
        }
      }
    }
  }
  dialog.showModal();
  if (currentSection === "projects") loadProjectAttachments(editingId);
  else document.querySelector("#writeup-panel").classList.add("hidden");
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
dialog.addEventListener("close", () => {
  if (thumbnailPreviewUrl) URL.revokeObjectURL(thumbnailPreviewUrl);
  thumbnailPreviewUrl = "";
});

entryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  entryMessage.textContent = "";
  const data = new FormData(entryForm);
  const payload = {};
  schema[currentSection].fields.forEach(([name, , type]) => {
    if (type === "file") return;
    const input = entryForm.elements.namedItem(name);
    payload[name] = input.type === "checkbox" ? input.checked : data.get(name);
  });
  payload.is_published = entryForm.elements.namedItem("is_published").checked;
  payload.sort_order = Number(data.get("sort_order") || 0);
  let uploadedFileId = null;
  try {
    const fileField = schema[currentSection].fileField;
    if (fileField) {
      const selectedFile = entryForm.elements.namedItem("attachment_upload").files?.[0];
      const removeAttachment = entryForm.elements.namedItem("remove_attachment").checked;
      const existingFileId = entryForm.elements.namedItem(fileField).value;
      if (selectedFile) {
        if (selectedFile.size > 5 * 1024 * 1024) throw new Error("Files must be 5 MB or smaller");
        if (currentSection === "projects" && fileField === "thumbnail_id" && !isValidThumbnail(selectedFile)) {
          throw new Error("Thumbnail must be an image (PNG, JPG, JPEG, or WEBP).");
        }
        const response = await fetch("/api/admin/files", {
          method: "POST",
          body: selectedFile,
          credentials: "same-origin",
          headers: {
            "Content-Type": selectedFile.type,
            "X-File-Name": encodeURIComponent(selectedFile.name),
            "X-CSRF-Token": csrfToken,
          },
        });
        const uploaded = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(uploaded.error || "File upload failed");
        uploadedFileId = uploaded.id;
        payload[fileField] = uploaded.id;
      } else if (removeAttachment) {
        payload[fileField] = null;
      } else {
        payload[fileField] = existingFileId ? Number(existingFileId) : null;
      }
    }
    const saved = await api(`/api/admin/${currentSection}${editingId ? `/${editingId}` : ""}`, {
      method: editingId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    uploadedFileId = null;
    if (currentSection === "projects" && !editingId) {
      editingId = saved.id;
      entryForm.elements.namedItem("slug").value = saved.slug;
      document.querySelector("#dialog-kicker").textContent = "EDIT ENTRY";
      document.querySelector("#dialog-title").textContent = "Edit project";
      entryMessage.textContent = "Project saved. You can now add write-ups above.";
      await loadProjectAttachments(editingId);
      await loadSection(currentSection);
      return;
    }
    dialog.close();
    await loadSection(currentSection);
  } catch (error) {
    if (uploadedFileId) {
      await api(`/api/admin/files/${uploadedFileId}`, { method: "DELETE" }).catch(() => {});
    }
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

initializeAdminPage();
