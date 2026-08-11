console.log("Dashboard Loaded");

const logoutBtn = document.getElementById("logoutBtn");
if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
        fetch("/api/logout", { method: "POST" })
            .then(() => {
                window.location.href = "/login";
            })
            .catch(() => {
                window.location.href = "/login";
            });
    });
}
