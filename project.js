const state = document.querySelector("#case-state");
const content = document.querySelector("#case-content");
const slug = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).at(-1) || "");

function addProjectLink(parent, label, url) {
  if (!url) return;
  const link = document.createElement("a");
  link.className = "text-link";
  link.href = url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.append(document.createTextNode(label));
  const arrow = document.createElement("span");
  arrow.textContent = "↗";
  link.append(arrow);
  parent.append(link);
}

function renderProject(project) {
  document.title = `${project.title} — Project Case Study`;
  document.querySelector("#case-title").textContent = project.title || "Untitled project";
  document.querySelector("#case-category").textContent = project.category || "PROJECT";
  document.querySelector("#case-summary").textContent = project.summary || "";
  document.querySelector("#case-description").textContent = project.description || project.summary || "";
  const tools = document.querySelector("#case-tools");
  tools.textContent = project.tools || "";
  document.querySelector("#case-tools-section").classList.toggle("hidden", !project.tools);
  const image = document.querySelector("#case-image");
  if (project.thumbnail_url) {
    image.src = project.thumbnail_url;
    image.alt = `${project.title} project thumbnail`;
    image.classList.remove("hidden");
  }
  const attachments = Array.isArray(project.write_ups) ? project.write_ups : [];
  const list = document.querySelector("#writeup-public-list");
  document.querySelector("#writeups-empty").classList.toggle("hidden", attachments.length > 0);
  attachments.forEach((attachment, index) => {
    const row = document.createElement("article");
    row.className = "writeup-public-row";
    const number = document.createElement("span");
    number.textContent = String(index + 1).padStart(2, "0");
    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = attachment.title;
    details.append(title);
    if (attachment.filename && attachment.filename !== attachment.title) {
      const filename = document.createElement("small");
      filename.className = "writeup-filename";
      filename.textContent = attachment.filename;
      details.append(filename);
    }
    const actions = document.createElement("div");
    actions.className = "writeup-actions";
    const view = document.createElement("a");
    view.className = "writeup-open";
    view.href = attachment.url;
    view.target = "_blank";
    view.rel = "noreferrer";
    view.textContent = attachment.media_type === "application/pdf" ? "VIEW WRITE-UP ↗" : "VIEW ATTACHMENT ↗";
    actions.append(view);
    if (attachment.media_type === "application/pdf") {
      const download = document.createElement("a");
      download.className = "writeup-download";
      download.href = attachment.url;
      download.download = attachment.filename || `${attachment.title || "write-up"}.pdf`;
      download.textContent = "DOWNLOAD PDF ↓";
      actions.append(download);
    }
    row.append(number, details, actions);
    list.append(row);
  });
  const links = document.querySelector("#case-links");
  addProjectLink(links, "GITHUB", project.github_url);
  addProjectLink(links, "EXTERNAL LINK", project.external_url);
  state.classList.add("hidden");
  content.classList.remove("hidden");
}

async function loadProject() {
  try {
    const response = await fetch(`/api/public/projects/${encodeURIComponent(slug)}`);
    if (response.status === 404) throw new Error("This project is unavailable or has not been published.");
    if (!response.ok) throw new Error("This project could not be loaded. Please try again later.");
    renderProject(await response.json());
  } catch (error) {
    state.textContent = error.message;
    state.classList.add("case-error");
  }
}

loadProject();
