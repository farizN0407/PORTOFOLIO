async function loadAboutProfileLinks() {
  try {
    const response = await fetch("/api/public/profile");
    if (!response.ok) throw new Error(`Profile could not be loaded (HTTP ${response.status})`);
    const profile = await response.json();
    for (const [selector, field] of [["#about-github-link", "github_url"], ["#about-linkedin-link", "linkedin_url"]]) {
      const link = document.querySelector(selector);
      if (!link || !profile[field]) continue;
      link.href = profile[field];
      link.classList.remove("hidden");
    }
  } catch (error) {
    console.error("About page contact links could not be loaded.", error);
  }
}

loadAboutProfileLinks();
