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

async function loadPortfolioContent() {
  const getItems = async (kind) => {
    const response = await fetch(`/api/public/${kind}`);
    if (!response.ok) throw new Error("Content could not be loaded");
    return response.json();
  };

  try {
    const [projects, certifications, activities] = await Promise.all([
      getItems("projects"),
      getItems("certifications"),
      getItems("activities"),
    ]);

    const projectList = document.querySelector("#project-list");
    projectList.replaceChildren();
    document.querySelector("#project-empty").classList.toggle("hidden", projects.length > 0);
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
      card.append(top, title, summary);
      if (project.tools) {
        const tools = document.createElement("p");
        tools.className = "project-tools";
        tools.textContent = project.tools;
        card.append(tools);
      }
      const links = document.createElement("div");
      links.className = "project-links";
      addExternalLink(links, "GITHUB", project.github_url);
      addExternalLink(links, "LEARN MORE", project.external_url);
      if (links.childNodes.length) card.append(links);
      projectList.append(card);
    });

    const certificationList = document.querySelector("#certification-list");
    certificationList.replaceChildren();
    document.querySelector("#certification-empty").classList.toggle("hidden", certifications.length > 0);
    document.querySelector("#certification-empty-copy").classList.toggle("hidden", certifications.length > 0);
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
      certificationList.append(row);
    });

    const activityList = document.querySelector("#activity-list");
    activityList.replaceChildren();
    activities.forEach((activity) => {
      const row = document.createElement("article");
      row.className = "activity-card";
      const mark = document.createElement("span");
      mark.className = "activity-mark";
      mark.textContent = activity.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
      const info = document.createElement("div");
      const role = document.createElement("span");
      role.className = "eyebrow";
      role.textContent = activity.role || "ACTIVITY";
      const name = document.createElement("h3");
      name.textContent = activity.name;
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
  } catch {
    // The page can still be previewed as a static file; managed content needs the local server.
  }
}

loadPortfolioContent();
