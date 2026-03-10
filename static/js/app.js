// ProviderVerify — app.js
// Minor global helpers; page-specific JS lives inline in templates.

// Auto-dismiss alerts after 5s
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".alert-dismissible").forEach(alert => {
    setTimeout(() => {
      const btn = alert.querySelector(".btn-close");
      if (btn) btn.click();
    }, 5000);
  });
});
