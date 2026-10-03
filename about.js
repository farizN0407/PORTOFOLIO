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

function setAboutGpa(profile) {
  const row = document.querySelector("#about-gpa-fact");
  const value = document.querySelector("#about-gpa-value");
  if (!row || !value) return;
  const number = profile.gpa === null || profile.gpa === "" || profile.gpa === undefined ? NaN : Number(profile.gpa);
  const hasGpa = Number.isFinite(number) && number >= 0 && number <= 4;
  row.classList.toggle("hidden", !hasGpa);
  value.textContent = hasGpa ? `${number.toFixed(2)} / 4.00` : "";
}

async function loadAboutProfileLinks() {
  try {
    const response = await fetch("/api/public/profile", { cache: "no-store" });
    if (!response.ok) throw new Error(`Profile could not be loaded (HTTP ${response.status})`);
    const profile = await response.json();
    setAboutGpa(profile);
    for (const [selector, field] of [["#about-github-link", "github_url"], ["#about-linkedin-link", "linkedin_url"]]) {
      const link = document.querySelector(selector);
      if (link) setAboutProfileLink(link, profile[field]);
    }
  } catch (error) {
    setAboutGpa({ gpa: null });
    document.querySelectorAll("#about-github-link, #about-linkedin-link").forEach((link) => {
      link.removeAttribute("href");
      link.classList.add("hidden");
    });
    console.error("About page contact links could not be loaded.", error);
  }
}

loadAboutProfileLinks();
