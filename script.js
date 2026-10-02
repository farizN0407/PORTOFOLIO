const menuButton = document.querySelector(".menu-toggle");
const navigation = document.querySelector(".primary-nav");

menuButton?.addEventListener("click", () => {
  const expanded = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", String(!expanded));
  menuButton.setAttribute("aria-label", expanded ? "Open navigation" : "Close navigation");
  navigation?.classList.toggle("is-open", !expanded);
});

navigation?.querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => {
    menuButton?.setAttribute("aria-expanded", "false");
    menuButton?.setAttribute("aria-label", "Open navigation");
    navigation.classList.remove("is-open");
  });
});

const revealTargets = document.querySelectorAll(
  ".section-label, .about-title-wrap, .about-copy, .focus-heading, .focus-bottom, .work-heading, .empty-work, .credentials-grid, .contact-section > *",
);

revealTargets.forEach((element) => element.classList.add("reveal"));

if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries, currentObserver) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          currentObserver.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12 },
  );

  revealTargets.forEach((element) => observer.observe(element));
} else {
  revealTargets.forEach((element) => element.classList.add("is-visible"));
}

function addExternalLink(parent, label, href) {
  if (!href) return;
  const link = document.createElement("a");
  link.className = "text-link dark-link";
  link.href = href;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.append(document.createTextNode(label));
  const arrow = document.createElement("span");
  arrow.textContent = "↗";
  link.append(arrow);
  parent.append(link);
}

function warnMissingElement(selector) {
  console.warn(`Portfolio content container ${selector} is missing; other sections will still load.`);
}

async function getPublicItems(kind) {
  const response = await fetch(`/api/public/${kind}`);
  if (!response.ok) throw new Error(`${kind} could not be loaded (HTTP ${response.status})`);
  const items = await response.json();
  if (!Array.isArray(items)) throw new Error(`${kind} API did not return a list`);
  return items;
}

function renderProjects(projects) {
  const projectList = document.querySelector("#project-list");
  const projectEmpty = document.querySelector("#project-empty");
  if (!projectList) warnMissingElement("#project-list");
  if (!projectEmpty) warnMissingElement("#project-empty");
  projectEmpty?.classList.toggle("hidden", projects.length > 0);
  if (!projectList) return;

  projectList.replaceChildren();
  projects.forEach((project, index) => {
    const card = document.createElement("article");
    card.className = "project-card";
    const top = document.createElement("div");
    top.className = "project-card-top";
    const number = document.createElement("span");
    number.textContent = String(index + 1).padStart(2, "0");
    const category = document.createElement("span");
    category.textContent = project.featured ? "FEATURED" : project.category || "PROJECT";
    top.append(number, category);
    const title = document.createElement("h3");
    title.textContent = project.title;
    const summary = document.createElement("p");
    summary.textContent = project.summary || project.description || "";
    card.append(top);
    if (project.thumbnail_url) {
      const image = document.createElement("img");
      image.className = "project-thumbnail";
      image.src = project.thumbnail_url;
      image.alt = `${project.title} preview`;
      image.loading = "lazy";
      card.append(image);
    }
    card.append(title, summary);
    if (project.tools) {
      const tools = document.createElement("p");
      tools.className = "project-tools";
      tools.textContent = project.tools;
      card.append(tools);
    }
    const links = document.createElement("div");
    links.className = "project-links";
    if (project.slug) {
      const caseStudy = document.createElement("a");
      caseStudy.className = "text-link dark-link";
      caseStudy.href = `/projects/${encodeURIComponent(project.slug)}`;
      caseStudy.append(document.createTextNode("VIEW PROJECT"));
      const arrow = document.createElement("span");
      arrow.textContent = "↗";
      caseStudy.append(arrow);
      links.append(caseStudy);
    }
    addExternalLink(links, "GITHUB", project.github_url);
    addExternalLink(links, "LEARN MORE", project.external_url);
    if (links.childNodes.length) card.append(links);
    projectList.append(card);
  });
}

function renderCertifications(certifications) {
  const certificationList = document.querySelector("#certification-list");
  const certificationEmpty = document.querySelector("#certification-empty");
  const certificationEmptyCopy = document.querySelector("#certification-empty-copy");
  if (!certificationList) warnMissingElement("#certification-list");
  if (!certificationEmpty) warnMissingElement("#certification-empty");
  if (!certificationEmptyCopy) warnMissingElement("#certification-empty-copy");
  const hasCertifications = certifications.length > 0;
  certificationEmpty?.classList.toggle("hidden", hasCertifications);
  certificationEmptyCopy?.classList.toggle("hidden", hasCertifications);
  if (!certificationList) return;

  certificationList.replaceChildren();
  certifications.forEach((certification) => {
    const row = document.createElement("article");
    row.className = "certification-card";
    const info = document.createElement("div");
    const name = document.createElement("h3");
    name.textContent = certification.name;
    const issuer = document.createElement("p");
    issuer.textContent = [certification.issuer, certification.date].filter(Boolean).join(" · ");
    info.append(name, issuer);
    row.append(info);
    addExternalLink(row, "VIEW CREDENTIAL", certification.credential_url);
    if (certification.certificate_file_url) {
      addExternalLink(row, "OPEN FILE", certification.certificate_file_url);
    }
    certificationList.append(row);
  });
}

function renderActivities(activities) {
  const activityList = document.querySelector("#activity-list");
  if (!activityList) {
    warnMissingElement("#activity-list");
    return;
  }

  activityList.replaceChildren();
  activities.forEach((activity) => {
    const row = document.createElement("article");
    row.className = "activity-card";
    const mark = document.createElement("span");
    mark.className = "activity-mark";
    mark.textContent = String(activity.name || "Activity").split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
    const info = document.createElement("div");
    const role = document.createElement("span");
    role.className = "eyebrow";
    role.textContent = activity.role || "ACTIVITY";
    const name = document.createElement("h3");
    name.textContent = activity.name || "Activity";
    const period = document.createElement("p");
    period.textContent = [activity.start_date, activity.end_date].filter(Boolean).join(" — ") || activity.description || "";
    info.append(role, name, period);
    row.append(mark, info);
    if (activity.url) {
      const link = document.createElement("a");
      link.className = "activity-arrow";
      link.href = activity.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.setAttribute("aria-label", "Visit activity link");
      link.textContent = "↗";
      row.append(link);
    }
    activityList.append(row);
  });
}

async function loadPortfolioSection(kind, render) {
  try {
    render(await getPublicItems(kind));
  } catch (error) {
    console.error(`Portfolio ${kind} section failed to load.`, error);
  }
}

function renderPublicProfile(profile) {
  const contactLinks = document.querySelector("#contact-links");
  const githubCta = document.querySelector("#contact-github-cta");
  const aboutGithub = document.querySelector("#about-github-cta");
  if (!contactLinks) return;
  contactLinks.replaceChildren();
  const addContact = (label, value, href, external = false) => {
    if (!value || !href) return;
    const link = document.createElement("a");
    link.className = "contact-item";
    link.href = href;
    if (external) { link.target = "_blank"; link.rel = "noreferrer"; }
    const kind = document.createElement("span");
    kind.className = "contact-item-label";
    kind.textContent = label;
    const text = document.createElement("strong");
    text.textContent = value;
    const arrow = document.createElement("span");
    arrow.className = "contact-item-arrow";
    arrow.textContent = "↗";
    link.append(kind, text, arrow);
    contactLinks.append(link);
  };
  addContact("EMAIL", profile.email, `mailto:${profile.email}`);
  const whatsapp = String(profile.whatsapp || "").replace(/\D/g, "");
  addContact("WHATSAPP", profile.whatsapp, whatsapp ? `https://wa.me/${whatsapp}` : "", true);
  addContact("LINKEDIN", profile.linkedin_url, profile.linkedin_url, true);
  addContact("GITHUB", profile.github_url, profile.github_url, true);
  addContact("PHONE", profile.phone, profile.phone ? `tel:${profile.phone.replace(/[^+0-9]/g, "")}` : "");
  if (githubCta) {
    githubCta.classList.toggle("hidden", !profile.github_url);
    if (profile.github_url) githubCta.href = profile.github_url;
  }
  if (aboutGithub) {
    aboutGithub.classList.toggle("hidden", !profile.github_url);
    if (profile.github_url) aboutGithub.href = profile.github_url;
  }
}

async function loadPublicProfile() {
  try {
    const response = await fetch("/api/public/profile");
    if (!response.ok) throw new Error(`Profile could not be loaded (HTTP ${response.status})`);
    renderPublicProfile(await response.json());
  } catch (error) {
    console.error("Portfolio profile could not be loaded.", error);
  }
}

async function loadPortfolioContent() {
  await Promise.all([
    loadPortfolioSection("projects", renderProjects),
    loadPortfolioSection("certifications", renderCertifications),
    loadPortfolioSection("activities", renderActivities),
    loadPublicProfile(),
  ]);
}

loadPortfolioContent();
