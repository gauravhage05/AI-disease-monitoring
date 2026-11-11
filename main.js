// GraniteCare AI — Main JavaScript
// Global utility functions shared across pages

document.addEventListener("DOMContentLoaded", () => {
    // Settings button wiring (in case base.html scripts run after block scripts)
    const settingsBtn = document.getElementById("settingsBtn");
    const settingsModal = document.getElementById("settingsModal");

    if (settingsBtn && settingsModal) {
        settingsBtn.addEventListener("click", () => {
            settingsModal.style.display = "flex";
        });
        settingsModal.addEventListener("click", (e) => {
            if (e.target.id === "settingsModal") settingsModal.style.display = "none";
        });
    }
});
