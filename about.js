function setAboutProfileLink(link, value) {
  link.removeAttribute("href");
  link.classList.add("hidden");
  const rawUrl = typeof value === "string" ? value.trim() : "";
  if (!rawUrl) return;

  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    return;
  }
  if (!["http:", "https:"].includes(url.protocol) || !url.hostname) return;

  link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.classList.remove("hidden");
}

async function loadAboutProfileLinks() {
  try {
    const response = await fetch("/api/public/profile", { cache: "no-store" });
    if (!response.ok) throw new Error(`Profile could not be loaded (HTTP ${response.status})`);
    const profile = await response.json();
    for (const [selector, field] of [["#about-github-link", "github_url"], ["#about-linkedin-link", "linkedin_url"]]) {
      const link = document.querySelector(selector);
      if (link) setAboutProfileLink(link, profile[field]);
    }
  } catch (error) {
    document.querySelectorAll("#about-github-link, #about-linkedin-link").forEach((link) => {
      link.removeAttribute("href");
      link.classList.add("hidden");
    });
    console.error("About page contact links could not be loaded.", error);
  }
}

loadAboutProfileLinks();
