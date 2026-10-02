// Add a LinkedIn profile URL here when it is ready; leave empty to show the placeholder.
const LINKEDIN_URL = "";
const placeholder = document.querySelector("#linkedin-placeholder");

if (LINKEDIN_URL && placeholder) {
  const link = document.createElement("a");
  link.href = LINKEDIN_URL;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "LINKEDIN ↗";
  placeholder.replaceWith(link);
}
